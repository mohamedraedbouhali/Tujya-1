"""The Tujya agent: an agentic RAG graph in LangGraph (docs/AGENT.md, D77).

    understand -> plan -> act -> grade --enough--> answer -> safety
                           ^          \\--weak--> refine --/   (at most agent_max_rounds)
        \\__________________ dose question: refuse ___________________/
        \\_ greeting, or off topic (grade) -> converse -> safety (D84)

- understand: drug names in the question (French or English) and the confirmed pills'
  ingredients, the topic of the question (contraindications, side effects, pregnancy...),
  language, and whether it asks for a dose (refused without any model call).
- plan: the first tool calls. Fast path ("auto", default): when the question names known
  drugs, rules choose the calls, with no LLM call. Otherwise the LLM plans (tool calling),
  and rules add what a question of that kind always needs.
- act: runs the planned calls concurrently and records each one.
- grade: turns the results into numbered sources and checks the evidence, without a model:
  a source about every drug asked about, the label section the question is about, PubMed
  abstracts when it asks for studies, and a dense hit similar enough to the question.
- refine: when the evidence is weak, the LLM agent sees what was searched, what was found
  and what is missing, and chooses new tool calls (an English query, other sections or
  document types, another tool); if it proposes nothing new, rules rewrite the search.
  Then act and grade again, up to `max_rounds` retrieval rounds in total.
- answer: the LLM answers from the numbered sources only, citing them; tokens are streamed
  sentence by sentence through the safety filter.
- safety: the rules of app/rag/safety.py on the whole answer; rewrite or refuse.
- converse (D84): a greeting ("hi", "merci") is answered at once, without searching. A
  question with no drug, no medical word and no confirmed pill is searched first; if even
  the best hit is far from it (below `topic_similarity`), it is not about medicines and the
  LLM answers briefly from general knowledge, marked as such, with the no-dose rule still on.

Speed (D78): no planner call on the fast path, concurrent tools, cached query embeddings
(app/rag/retrieval.py), and an answer cache: the same question with the same pills gets the
checked answer again without any model call.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.medicines import DISCLAIMER, pill_infos
from app.rag.converse import (
    CONVERSE_FALLBACK,
    CONVERSE_PROMPT,
    CYRILLIC,
    FOLLOW_UP,
    MEDICAL,
    RU_DOSE,
    SMALL_TALK,
)
from app.rag.embeddings import EmbeddingError, fold
from app.rag.safety import (
    CROSS_REFERENCE,
    REFUSAL_DOSE,
    SentenceFilter,
    attribute_by_meaning,
    check_answer,
    is_dose_question,
    sentence_problems,
    split_sentences,
)
from app.rag.tools import CHAT_TOOLS, Toolbox, ToolError, langchain_tools
from app.toxicity import LOW_NOTE, MIXTURE_NOTE, WORDING

MAX_SOURCES = 8
# A question about toxicity gets predict_toxicity even if the planner forgets it (folded text).
TOXICITY_QUESTION = re.compile(r"\btoxi\w*|\btox21\b|\bin vitro\b")
# An answer sentence about the prediction (folded text): toxicity words, assays, Tox21 tasks.
TOX_MENTION = re.compile(r"\btoxi\w*|\btox21\b|\bin vitro\b|\bassays?\b|\b(?:nr|sr)-\w+")
MAX_TOOL_CALLS = 6
SOURCE_CHARS = 900
MAX_CHECKED_DRUGS = 3  # the evidence check looks at the first three drugs asked about
FRENCH_HINTS = frozenset(
    [
        "le",
        "la",
        "les",
        "des",
        "est",
        "une",
        "avec",
        "quels",
        "quelles",
        "quel",
        "quelle",
        "peut",
        "entre",
        "interaction",
        "effets",
        "indesirables",
        "prendre",
        "puis",
        "je",
        "mon",
        "ma",
        "mes",
        "et",
        "ou",
        "pour",
        "sur",
        "contre",
        "qui",
        "quoi",
        "pourquoi",
        "bonjour",
        "bonsoir",
        "salut",
        "merci",
        "tu",
        "vous",
        "moi",
        "sont",
        "dans",
        "du",
        "aux",
    ]
)

# Topic of a question (folded text) -> the label sections that answer it, and English words
# for a rewritten search query. Several topics can match one question.
# fmt: off
INTENTS: tuple[tuple[str, re.Pattern[str], tuple[str, ...], str], ...] = (
    ("boxed_warning", re.compile(r"boxed warning|black box|encadre"), ("boxed_warning",),
     "boxed warning"),
    ("contraindications", re.compile(r"contre[- ]?indi\w*|contraindicat\w*"),
     ("contraindications",), "contraindications"),
    ("adverse_reactions",
     re.compile(r"effets? (?:indesirables?|secondaires?)|side[- ]?effects?|"
                r"adverse (?:reactions?|effects?|events?)"),
     ("adverse_reactions",), "adverse reactions side effects"),
    ("mechanism", re.compile(r"mecanisme|mechanism|comment (?:agit|fonctionne)|how does \w+ work"),
     ("mechanism_of_action",), "mechanism of action"),
    ("warnings", re.compile(r"\bprecautions?\b|mises? en garde|(?<!boxed )\bwarnings?\b"),
     ("warnings_and_cautions", "warnings", "precautions", "general_precautions"),
     "warnings precautions"),
    ("pregnancy", re.compile(r"grossesse|enceinte|pregnan\w*"),
     ("pregnancy", "use_in_specific_populations"), "pregnancy"),
    ("lactation", re.compile(r"allait\w*|breast[- ]?feed\w*|lactation|nursing"),
     ("lactation", "nursing_mothers", "use_in_specific_populations"), "lactation breastfeeding"),
    ("pediatric", re.compile(r"\benfants?\b|pediatri\w*|\bchild(?:ren)?\b"),
     ("pediatric_use", "use_in_specific_populations"), "pediatric use children"),
    ("geriatric",
     re.compile(r"personnes? agees?|sujets? ages?|elderly|geriatri\w*|older (?:adults|patients)"),
     ("geriatric_use", "use_in_specific_populations"), "geriatric use elderly"),
    ("indications",
     re.compile(r"(?<!contre-)(?<!contre )\bindications?\b|utilise pour|sert a|used for"),
     ("indications_and_usage",), "indications and usage"),
)
# fmt: on
LITERATURE = re.compile(
    r"\betudes?\b|\barticles?\b|\bpublications?\b|\bstud(?:y|ies)\b|\btrials?\b|"
    r"case reports?|cas (?:rapportes?|cliniques?)|meta[- ]?analys\w*|"
    r"\brevues?\b|\breviews?\b|pubmed"
)


class AgentState(TypedDict, total=False):
    question: str
    pills: list[int]
    language: str
    ingredients: list[str]  # named in the question, then the confirmed pills' ingredients
    question_ingredients: list[str]  # named in the question only
    intents: list[str]
    literature: bool
    pill_labels: list[str]
    dose_question: bool
    # "documents" (cited answer), "check" (search first, then decide), "small_talk" (greeting)
    # or "general" (off topic, answered from general knowledge), D84.
    route: str
    llm_model: str  # the model that wrote the answer: Groq, or the local fallback (D86)
    reply_language: str  # of a general answer: Russian too, when asked in Russian
    planner: str
    round: int
    pending: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    evidence: dict[str, Any]
    draft: str
    answer: str
    safety: dict[str, Any]
    agent: dict[str, Any]
    timings: dict[str, float]


def detect_language(question: str) -> str:
    words = re.findall(r"[a-z]+", fold(question))
    french = sum(1 for w in words if w in FRENCH_HINTS)
    accents = bool(re.search(r"[éèêàùçôîâ]", question.lower()))
    # A short message is French when most of its words are ("bonjour", "merci beaucoup").
    mostly = bool(words) and french * 2 >= len(words)
    return "fr" if french >= 2 or accents or mostly else "en"


def route_of(question: str, *, asked: list[str], pills: list[int], check: bool) -> str:
    """Where a question goes before any search (D84); "check" means: search, then decide."""
    folded = fold(question)
    medical = (
        asked
        or detect_intents(question)
        or LITERATURE.search(folded)
        or TOXICITY_QUESTION.search(folded)
        or MEDICAL.search(folded)
        or is_dose_question(question)
    )
    if medical:
        return "documents"
    if SMALL_TALK.match(folded):
        return "small_talk"
    # A follow-up about the confirmed pills ("and together?") stays with the documents;
    # anything else asked next to them ("trump") is checked like any other question.
    if (pills and FOLLOW_UP.search(folded)) or not check:
        return "documents"
    return "check"


def detect_intents(question: str) -> list[str]:
    folded = fold(question)
    return [name for name, pattern, _, _ in INTENTS if pattern.search(folded)]


def intent_sections(intents: list[str]) -> tuple[str, ...]:
    wanted: list[str] = []
    for name, _, sections, _ in INTENTS:
        if name in intents:
            wanted += [s for s in sections if s not in wanted]
    return tuple(wanted)


def intent_topics(intents: list[str]) -> list[str]:
    return [topic for name, _, _, topic in INTENTS if name in intents]


LEADING_CITATIONS = re.compile(r"^(?:\[\d+\]\s*)+")


def strip_source_echo(draft: str, sources: list[dict[str, Any]]) -> str:
    """A 3B model sometimes opens its answer by repeating citation numbers or a source's
    header ("[1] [2] [6] Warfarin..." or "[1] Losartan label (...): Nursing mothers (openFDA
    drug label, 20260804) It is..."). Both are removed; the sentences keep their own
    citations."""
    text = draft.lstrip()
    while True:
        before = text
        text = LEADING_CITATIONS.sub("", text).lstrip()
        for source in sources:
            head = f"{source['title']} ({source['source_name']}"
            if text.startswith(head):
                close = text.find(")", len(head))
                if close != -1:
                    text = text[close + 1 :].lstrip(" :.-\n")
                break
        if text == before:
            return text


def signature(name: str, args: dict[str, Any]) -> str:
    """Identity of a tool call, to never run the same call twice in one question."""
    return f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"


TOOLS_PROMPT = """You are the tool planner of Tujya, a medicine-information assistant.
Call the tools needed to answer the user's question about medicines:
- check_interaction when the question is about two or more drugs together;
- get_drug_info for facts about one drug (contraindications, warnings, mechanism);
- search_documents for anything else, with an English query and the drug names as filters;
- predict_toxicity only when the question is about toxicity (one or two molecules).
Use the active ingredient names given. Do not answer the question yourself."""

REFINE_PROMPT = """You are the retrieval agent of Tujya, a medicine-information assistant.
The first search did not find everything needed to answer the question. Call tools again to
find what is missing:
- search_documents with a short ENGLISH query (drug names and topic words), the drug names as
  `ingredients`, and `sections` or `doc_types` when the topic is clear (for example sections
  ["contraindications"], or doc_types ["abstract"] for studies);
- get_drug_info for one drug and the label sections needed;
- check_interaction when two drugs are involved and it was not called yet.
Never repeat a call already made. Do not answer the question yourself."""

ANSWER_PROMPT = {
    "fr": """Tu es Tujya, un assistant d'information sur les médicaments. Réponds en français.
Règles absolues :
- Réponds UNIQUEMENT à partir des sources numérotées ci-dessous. Si elles ne répondent pas, dis-le.
- Chaque phrase se termine par le numéro de la source qui la soutient, entre crochets.
  Exemple : « La metformine est contre-indiquée en cas d'insuffisance rénale sévère [2]. »
- Ne donne JAMAIS de dose, de posologie, de nombre de comprimés ou de fréquence de prise.
- N'écris JAMAIS qu'une association est « sûre » ou « sans danger ». S'il n'y a pas d'interaction
  dans les sources, écris : « aucune interaction connue dans cette base de données ».
- Ne donne aucun conseil d'horaire ou d'espacement des prises sauf si une source le dit ; cite-la.
- 3 à 6 phrases courtes, sans titre ni liste : d'abord la réponse directe (par exemple
  la sévérité DDInter), puis ce que disent les notices ou les articles (mécanisme, effets,
  surveillance).""",
    "en": """You are Tujya, a medicine-information assistant. Answer in English.
Absolute rules:
- Answer ONLY from the numbered sources below. If they do not answer, say so.
- Every sentence ends with the number of the source that supports it, in brackets.
  Example: "Metformin is contraindicated in severe renal impairment [2]."
- NEVER give a dose, a dosage, a number of tablets or how often to take a medicine.
- NEVER write that a combination is "safe". If the sources show no interaction, write:
  "no known interaction in this database".
- Give no timing or spacing advice unless a source says it; cite it.
- 3 to 6 short sentences, no heading, no list: first the direct answer (e.g. the DDInter
  severity), then what the labels or articles say (mechanism, effects, monitoring).""",
}


def _summary(name: str, result: dict[str, Any] | None, error: str | None) -> str:
    if error:
        return f"error: {error}"
    assert result is not None
    if name == "check_interaction":
        return str(result.get("message", ""))
    if name == "search_documents":
        return f"{len(result.get('results', []))} documents"
    if name == "get_drug_info":
        return (
            f"{result.get('ingredient')}: {len(result.get('pill_classes', []))} pill classes, "
            f"{len(result.get('label_sections', []))} label sections"
        )
    if name == "predict_toxicity":
        names = [m.get("ingredient") or m.get("query") for m in result.get("molecules", [])]
        return f"{WORDING}: {', '.join(names) or 'no valid molecule'}"
    return "ok"


def toxicity_sources(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Each molecule predicted by predict_toxicity, as a citable source (never a mixture)."""
    found = []
    source = result.get("source", {})
    for molecule in result.get("molecules", []):
        name = molecule.get("ingredient") or molecule.get("query")
        values = "; ".join(
            f"{p['task']} {p['probability']:.2f} (ROC-AUC {p['test_roc_auc']})"
            for p in molecule.get("predictions", [])
        )
        domain = (
            ""
            if molecule.get("in_domain", True)
            else " The molecule is far from the training molecules (low similarity): the "
            "prediction is even less reliable."
        )
        # The caveats come first: the prompt keeps only the start of each source.
        text = (
            f"Tox21 model, {WORDING}. {MIXTURE_NOTE} {LOW_NOTE}{domain} {name}: probability "
            f"of being active in each Tox21 in vitro assay (model test ROC-AUC): {values}."
        )
        found.append(
            {
                "chunk_id": f"tox21:{name}",
                "doc_type": "prediction",
                "title": f"Tox21 model (in vitro, not clinical): {name}",
                "section": "toxicity_prediction",
                "url": source.get("url", "https://tripod.nih.gov/tox21/challenge/"),
                "source_name": f"Tujya model tujya-tox21 v{result.get('model', {}).get('version')}",
                "date": "",
                "license": "",
                "ingredients": [name] if name else [],
                "text": text,
                "snippet": text,
            }
        )
    return found


def interaction_sources(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Each DDInter interaction found by check_interaction, as a citable source."""
    found = []
    for pair in result.get("pairs", []):
        for row in pair.get("interactions", []):
            source = row.get("source", {})
            found.append(
                {
                    "chunk_id": f"ddinter:{row['ingredient_a']}:{row['ingredient_b']}",
                    "doc_type": "interaction",
                    "title": f"DDInter 2.0: {row['ingredient_a']} + {row['ingredient_b']} "
                    f"({row['severity']})",
                    "section": "interaction",
                    "url": source.get("url", "https://ddinter2.scbdd.com/"),
                    "source_name": source.get("title", "DDInter 2.0"),
                    "date": "",
                    "license": source.get("license", ""),
                    "ingredients": [row["ingredient_a"], row["ingredient_b"]],
                    "text": row.get("description", ""),
                    "snippet": row.get("description", ""),
                }
            )
        if not pair.get("interactions") and pair.get("message"):
            item_a, item_b = pair["item_a"], pair["item_b"]
            a, b = item_a["label"], item_b["label"]
            found.append(
                {
                    "chunk_id": f"ddinter-none:{a}:{b}",
                    "doc_type": "interaction",
                    "title": f"DDInter 2.0: {a} + {b}",
                    "section": "interaction",
                    "url": "https://ddinter2.scbdd.com/",
                    "source_name": "DDInter 2.0 (Tujya database)",
                    "date": "",
                    "license": "CC BY-NC-SA 4.0",
                    "ingredients": [
                        *(item_a.get("active_ingredients") or [a]),
                        *(item_b.get("active_ingredients") or [b]),
                    ],
                    "text": f"{a} + {b}: {pair['message']}",
                    "snippet": f"{a} + {b}: {pair['message']}",
                }
            )
    return found


ACTIVE_AT = 0.5  # reading aid only: the summary lists the assays at or above it


def prediction_numbers(state: AgentState) -> set[int]:
    return {s["n"] for s in state.get("sources", []) if s.get("doc_type") == "prediction"}


def about_prediction(sentence: str, numbers: set[int]) -> bool:
    """A sentence citing a toxicity prediction or talking about toxicity / the assays."""
    cites = {int(n) for n in re.findall(r"\[(\d+)\]", sentence)}
    return bool(cites & numbers) or bool(TOX_MENTION.search(fold(sentence)))


def toxicity_summary(state: AgentState) -> tuple[str, list[int]]:
    """A fixed, cited sentence per predicted molecule, written from the tool output (not by
    the LLM), so the numbers and the in vitro caveat are always right in the answer."""
    numbers = {s["chunk_id"]: s["n"] for s in state.get("sources", []) if "n" in s}
    french = state.get("language", "fr") == "fr"
    sentences, cited = [], []
    for entry in state.get("tool_results", []):
        if entry["name"] != "predict_toxicity" or not entry["result"]:
            continue
        for molecule in entry["result"].get("molecules", []):
            name = molecule.get("ingredient") or molecule.get("query")
            n = numbers.get(f"tox21:{name}")
            if n is None:
                continue
            high = [p for p in molecule.get("predictions", []) if p["probability"] >= ACTIVE_AT]
            listed = ", ".join(f"{p['task']} ({p['probability']:.2f})" for p in high)
            if french:
                found = (
                    f"probabilité d'activité d'au moins 0,5 dans {len(high)} des 12 tests : "
                    f"{listed}".replace(".", ",")
                    if high
                    else "aucun des 12 tests n'atteint une probabilité d'activité de 0,5, ce qui "
                    "ne prouve pas l'absence de toxicité"
                )
                sentences.append(f"Modèle Tox21 pour {name} ({WORDING}) : {found} [{n}].")
            else:
                found = (
                    f"probability of activity of at least 0.5 in {len(high)} of the 12 assays: "
                    f"{listed}"
                    if high
                    else "none of the 12 assays reaches a probability of activity of 0.5, which "
                    "does not show an absence of toxicity"
                )
                sentences.append(
                    f"Tox21 model for {name} (a model prediction on in vitro tests, not a "
                    f"clinical evaluation): {found} [{n}]."
                )
            cited.append(n)
    return " ".join(sentences), cited


class AnswerCache:
    """Checked answers by (question, pills, index version, model), least recently used out."""

    def __init__(self, size: int, seconds: float) -> None:
        self.size, self.seconds = size, seconds
        self._items: OrderedDict[tuple[Any, ...], tuple[float, AgentState]] = OrderedDict()

    def get(self, key: tuple[Any, ...]) -> AgentState | None:
        item = self._items.get(key)
        if item is None:
            return None
        stored, state = item
        if time.monotonic() - stored >= self.seconds:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return copy.deepcopy(state)

    def put(self, key: tuple[Any, ...], state: AgentState) -> None:
        if self.size <= 0:
            return
        self._items[key] = (time.monotonic(), copy.deepcopy(state))
        self._items.move_to_end(key)
        while len(self._items) > self.size:
            self._items.popitem(last=False)


class TujyaAgent:
    def __init__(
        self,
        llm: BaseChatModel | Runnable[Any, Any],
        toolbox: Toolbox,
        *,
        top_k: int = 6,
        attribution_threshold: float = 0.0,
        planner: str = "auto",
        max_rounds: int = 2,
        min_similarity: float = 0.0,
        topic_similarity: float = 0.0,
        cache_size: int = 0,
        cache_seconds: float = 3600,
    ) -> None:
        self.llm, self.toolbox, self.top_k = llm, toolbox, top_k
        self.attribution_threshold = attribution_threshold
        self.planner_mode = planner if planner in ("auto", "llm", "rules") else "auto"
        self.max_rounds = max(1, max_rounds)
        self.min_similarity = min_similarity
        self.topic_similarity = topic_similarity
        self.cache = AnswerCache(cache_size, cache_seconds)
        self.tools = {t.name: t for t in langchain_tools(toolbox, CHAT_TOOLS)}
        self._planner: Any = None
        graph = StateGraph(AgentState)
        graph.add_node("understand", self.understand)
        graph.add_node("plan", self.plan)
        graph.add_node("act", self.act)
        graph.add_node("grade", self.grade)
        graph.add_node("refine", self.refine)
        graph.add_node("answer", self.answer)
        graph.add_node("safety", self.safety)
        graph.add_node("converse", self.converse)
        graph.add_edge(START, "understand")
        graph.add_conditional_edges(
            "understand",
            self.after_understand,
            {"safety": "safety", "plan": "plan", "converse": "converse"},
        )
        graph.add_edge("plan", "act")
        graph.add_edge("act", "grade")
        graph.add_conditional_edges(
            "grade",
            self.after_grade,
            {"answer": "answer", "refine": "refine", "converse": "converse"},
        )
        graph.add_edge("refine", "act")
        graph.add_edge("answer", "safety")
        graph.add_edge("converse", "safety")
        graph.add_edge("safety", END)
        self.graph = graph.compile()

    # -------------------------------------------------------------- helpers

    def planner_model(self) -> Any:
        if self._planner is None:
            self._planner = self.llm.bind_tools(list(self.tools.values()))
        return self._planner

    async def _llm_calls(
        self, system: str, context: str, done: set[str]
    ) -> list[dict[str, Any]] | None:
        """Tool calls chosen by the LLM (None if the call failed), minus calls already made."""
        try:
            message = await self.planner_model().ainvoke(
                [SystemMessage(system), HumanMessage(context)]
            )
            raw = getattr(message, "tool_calls", []) or []
        except Exception:
            return None
        calls, seen = [], set(done)
        for call in raw:
            name, args = call.get("name"), dict(call.get("args") or {})
            if name not in self.tools or signature(name, args) in seen:
                continue
            seen.add(signature(name, args))
            calls.append({"name": name, "args": args, "by": "llm"})
        return calls[:MAX_TOOL_CALLS]

    def _toxicity_question(self, state: AgentState) -> bool:
        return bool(
            TOXICITY_QUESTION.search(fold(state["question"]))
            and "predict_toxicity" in self.tools
            and state.get("ingredients")
        )

    def _search_args(self, state: AgentState) -> dict[str, Any]:
        args: dict[str, Any] = {"query": state["question"], "ingredients": state["ingredients"]}
        if state.get("literature"):
            args["doc_types"] = ["abstract"]
        return args

    def _rule_plan(self, state: AgentState) -> list[dict[str, Any]]:
        """The fast path: the calls a question naming known drugs needs, without the LLM."""
        ingredients = state.get("ingredients", [])
        asked = state.get("question_ingredients") or ingredients
        sections = intent_sections(state.get("intents", []))
        calls: list[dict[str, Any]] = []
        if len(ingredients) >= 2:
            calls.append({"name": "check_interaction", "args": {"drugs": ingredients}})
        if self._toxicity_question(state):
            calls.append({"name": "predict_toxicity", "args": {"molecules": ingredients[:2]}})
        elif len(asked) == 1 or sections:
            for drug in asked[:2]:
                args: dict[str, Any] = {"drug": drug}
                if sections:
                    args["sections"] = list(sections)
                calls.append({"name": "get_drug_info", "args": args})
        calls.append({"name": "search_documents", "args": self._search_args(state)})
        return [{**call, "by": "rule"} for call in calls if call["name"] in self.tools]

    def _minimum_calls(
        self, state: AgentState, planned: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """What the graph adds when the LLM planned: the calls a question always needs."""
        names = {c["name"] for c in planned}
        ingredients = state.get("ingredients", [])
        added = []
        if len(ingredients) >= 2 and "check_interaction" not in names:
            added.append({"name": "check_interaction", "args": {"drugs": ingredients}})
        if self._toxicity_question(state) and "predict_toxicity" not in names:
            added.append({"name": "predict_toxicity", "args": {"molecules": ingredients[:2]}})
        if "search_documents" not in names:
            added.append({"name": "search_documents", "args": self._search_args(state)})
        return [{**call, "by": "rule"} for call in added]

    def _rule_refine(self, state: AgentState, done: set[str]) -> list[dict[str, Any]]:
        """A rewritten search when the LLM agent proposes nothing new: English drug names and
        topic words, the topic's label sections, PubMed only when studies are asked for."""
        asked = (state.get("question_ingredients") or state.get("ingredients", []))[:3]
        intents = state.get("intents", [])
        topics = intent_topics(intents) or (["drug interactions"] if len(asked) >= 2 else [])
        args: dict[str, Any] = {"query": " ".join([*asked, *topics]) or state["question"]}
        if asked:
            args["ingredients"] = asked
        if intent_sections(intents):
            args["sections"] = list(intent_sections(intents))
        if state.get("literature"):
            args["doc_types"] = ["abstract"]
        calls = [{"name": "search_documents", "args": args}]
        covered = {
            name
            for s in state.get("sources", [])
            if s.get("doc_type") == "label"
            for name in s.get("ingredients") or []
        }
        calls += [{"name": "get_drug_info", "args": {"drug": n}} for n in asked if n not in covered]
        return [
            {**call, "by": "rule"}
            for call in calls
            if call["name"] in self.tools and signature(call["name"], call["args"]) not in done
        ][:MAX_TOOL_CALLS]

    def _collect(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Numbered sources [1], [2]...: DDInter first, then toxicity predictions, label
        sections, search hits; the latest round's results before the earlier ones."""
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(items: list[dict[str, Any]], limit: int) -> None:
            for item in items[:limit]:
                if item["chunk_id"] not in seen and len(sources) < MAX_SOURCES:
                    seen.add(item["chunk_id"])
                    sources.append(dict(item))

        latest_first = sorted(
            (e for e in results if e["result"]), key=lambda e: -int(e.get("round", 1))
        )
        for entry in latest_first:
            if entry["name"] == "check_interaction":
                add(interaction_sources(entry["result"]), 3)
        for entry in latest_first:
            if entry["name"] == "predict_toxicity":
                add(toxicity_sources(entry["result"]), 2)
        for entry in latest_first:
            if entry["name"] == "get_drug_info":
                add(entry["result"].get("label_sections", []), 2)
        for entry in latest_first:
            if entry["name"] == "search_documents":
                add(entry["result"].get("results", []), self.top_k)
        for number, source in enumerate(sources, start=1):
            source["n"] = number
        return sources

    def _evidence(self, state: AgentState, sources: list[dict[str, Any]]) -> dict[str, Any]:
        """Is there enough to answer? Rules only (no model call), so the check costs nothing."""
        missing: list[str] = []
        if not sources:
            missing.append("no source found")
        retriever = self.toolbox.retrievers.get()
        in_corpus = retriever.ingredients if retriever is not None else set()
        label_sections = retriever.label_sections if retriever is not None else {}
        asked = (state.get("question_ingredients") or state.get("ingredients", []))[
            :MAX_CHECKED_DRUGS
        ]

        def about(source: dict[str, Any]) -> set[str]:
            return {
                *(source.get("ingredients") or []),
                *(source.get("mentioned_ingredients") or []),
            }

        for name in asked:
            # A drug the corpus has nothing about cannot be found by searching again.
            if name in in_corpus and not any(name in about(s) for s in sources):
                missing.append(f"nothing about {name}")
        for intent in state.get("intents", []):
            sections = intent_sections([intent])
            available = [n for n in asked if any((n, s) in label_sections for s in sections)]
            if available and not any(
                s.get("section") in sections and set(available) & about(s) for s in sources
            ):
                missing.append(f"no {intent} section of the label")
        if state.get("literature") and not any(s.get("doc_type") == "abstract" for s in sources):
            missing.append("no PubMed abstract")
        # From the search results themselves: a hit that repeats a label excerpt is kept once
        # in the sources, without its similarity.
        similarities = [
            hit["similarity"]
            for entry in state.get("tool_results", [])
            if entry["name"] == "search_documents" and entry["result"]
            for hit in entry["result"].get("results", [])
            if hit.get("similarity") is not None
        ]
        best = max(similarities) if similarities else None
        if best is not None and self.min_similarity > 0 and best < self.min_similarity:
            missing.append(f"weak search matches (best similarity {best:.2f})")
        return {
            "enough": not missing,
            "missing": missing,
            "best_similarity": None if best is None else round(best, 4),
            "sources": len(sources),
        }

    def _cache_key(self, question: str, pills: list[int] | None) -> tuple[Any, ...]:
        text = " ".join(fold(question).split())
        version = getattr(self.toolbox.retrievers, "version", None)
        model = getattr(self.llm, "model", None) or type(self.llm).__name__
        return (text, tuple(sorted(pills or [])), version, model)

    # -------------------------------------------------------------- nodes

    async def understand(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        question = state["question"]
        found = self.toolbox.names().find(question)
        asked = list(found)
        labels: list[str] = []
        pills = state.get("pills", [])
        if pills:
            with Session(self.toolbox.pharma_engine) as session:
                infos = pill_infos(session, pills)
            for class_id in pills:
                info = infos.get(class_id)
                if info:
                    labels.append(f"{info.name} ({', '.join(info.ingredients) or '?'})")
                    found += [i for i in info.ingredients if i not in found]
        return {
            "language": detect_language(question),
            "ingredients": found,
            "question_ingredients": asked,
            "intents": detect_intents(question),
            "literature": bool(LITERATURE.search(fold(question))),
            "pill_labels": labels,
            "dose_question": is_dose_question(question),
            "route": route_of(question, asked=asked, pills=pills, check=self.topic_similarity > 0),
            "tool_calls": [],
            "tool_results": [],
            "timings": {"understand_ms": _ms(started)},
        }

    async def plan(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        ingredients = state.get("ingredients", [])
        use_llm = state.get("route") != "check" and (
            self.planner_mode == "llm" or (self.planner_mode == "auto" and not ingredients)
        )
        if use_llm:
            context = (
                f"Question: {state['question']}\n"
                f"Active ingredients mentioned or confirmed: {', '.join(ingredients) or 'none'}"
            )
            planned = await self._llm_calls(TOOLS_PROMPT, context, set())
            planner = "llm" if planned is not None else "rules (planner failed)"
            calls = (planned or []) + self._minimum_calls(state, planned or [])
        else:
            planner, calls = "rules", self._rule_plan(state)
        timings = {**state.get("timings", {}), "plan_ms": _ms(started)}
        return {"pending": calls, "planner": planner, "round": 1, "timings": timings}

    async def act(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        writer = get_stream_writer()
        round_number = state.get("round", 1)
        done = {signature(c["name"], c["args"]) for c in state.get("tool_calls", [])}
        todo, seen = [], set(done)
        for call in state.get("pending", []):
            key = signature(call["name"], call["args"])
            if key not in seen:
                seen.add(key)
                todo.append(call)

        async def run(call: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            result, error = None, None
            try:
                result = await self.tools[call["name"]].ainvoke(call["args"])
            except ToolError as exc:
                error = str(exc)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:300]
            record = {
                "name": call["name"],
                "args": call["args"],
                "chosen_by": call["by"],
                "ok": error is None,
                "summary": _summary(call["name"], result, error),
                "round": round_number,
            }
            writer({"type": "tool", "tool": record})
            return record, {"name": call["name"], "result": result, "round": round_number}

        finished = await asyncio.gather(*(run(call) for call in todo))
        timings = dict(state.get("timings", {}))
        timings["tools_ms"] = round(timings.get("tools_ms", 0.0) + _ms(started), 1)
        return {
            "tool_calls": [*state.get("tool_calls", []), *(r for r, _ in finished)],
            "tool_results": [*state.get("tool_results", []), *(e for _, e in finished)],
            "pending": [],
            "timings": timings,
        }

    async def grade(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        sources = self._collect(state.get("tool_results", []))
        evidence = self._evidence(state, sources)
        timings = dict(state.get("timings", {}))
        timings["grade_ms"] = round(timings.get("grade_ms", 0.0) + _ms(started), 1)
        return {"sources": sources, "evidence": evidence, "timings": timings}

    def after_understand(self, state: AgentState) -> str:
        if state.get("dose_question"):
            return "safety"
        return "converse" if state.get("route") == "small_talk" else "plan"

    def after_grade(self, state: AgentState) -> str:
        if state.get("route") == "check" and state.get("round", 1) == 1:
            best = state.get("evidence", {}).get("best_similarity")
            if best is None or best < self.topic_similarity:
                return "converse"  # nothing in the documents is close: not about medicines
        if state.get("evidence", {}).get("enough") or state.get("round", 1) >= self.max_rounds:
            return "answer"
        return "refine"

    async def refine(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        done = {signature(c["name"], c["args"]) for c in state.get("tool_calls", [])}
        made = "\n".join(
            f"- {c['name']}({json.dumps(c['args'], ensure_ascii=False)}): {c['summary']}"
            for c in state.get("tool_calls", [])
        )
        found = "\n".join(
            f"- [{s['n']}] {s['title']} ({s.get('section', '')})" for s in state.get("sources", [])
        )
        context = (
            f"Question: {state['question']}\n"
            f"Active ingredients: {', '.join(state.get('ingredients', [])) or 'none'}\n"
            f"Calls already made:\n{made or '- none'}\n"
            f"Sources found:\n{found or '- none'}\n"
            f"Missing: {'; '.join(state.get('evidence', {}).get('missing', []))}"
        )
        calls = await self._llm_calls(REFINE_PROMPT, context, done) or []
        if not calls:
            calls = self._rule_refine(state, done)
        timings = dict(state.get("timings", {}))
        timings["refine_ms"] = round(timings.get("refine_ms", 0.0) + _ms(started), 1)
        return {"pending": calls, "round": state.get("round", 1) + 1, "timings": timings}

    def _answer_messages(self, state: AgentState) -> list[Any]:
        language = state.get("language", "fr")
        blocks = []
        for source in state.get("sources", []):
            text = CROSS_REFERENCE.sub("", source.get("text") or source.get("snippet") or "")
            blocks.append(
                f"[{source['n']}] {source['title']} ({source['source_name']}"
                f"{', ' + source['date'] if source.get('date') else ''})\n{text[:SOURCE_CHARS]}"
            )
        pills = state.get("pill_labels", [])
        context = "\n\n".join(blocks)
        user = (
            f"Comprimés confirmés : {'; '.join(pills)}\n" if pills else ""
        ) + f"Sources :\n{context}\n\nQuestion : {state['question']}"
        return [SystemMessage(ANSWER_PROMPT[language]), HumanMessage(user)]

    async def answer(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        if not state.get("sources"):
            return {"draft": "", "timings": {**state.get("timings", {}), "answer_ms": 0.0}}
        writer = get_stream_writer()
        # With a toxicity prediction, its sentences come from toxicity_summary, not the LLM.
        numbers = prediction_numbers(state)
        sentences = SentenceFilter(
            hold=(lambda s: about_prediction(s, numbers)) if numbers else None
        )
        parts: list[str] = []
        first_token: float | None = None
        model: str | None = None
        async for chunk in self.llm.astream(self._answer_messages(state)):
            model = model_of(chunk) or model
            text = chunk.content if isinstance(chunk.content, str) else ""
            if not text:
                continue
            if first_token is None:
                first_token = _ms(started)
            parts.append(text)
            for sentence in sentences.feed(text):
                writer({"type": "token", "text": sentence})
        for sentence in sentences.flush():
            writer({"type": "token", "text": sentence})
        timings = {**state.get("timings", {}), "answer_ms": _ms(started)}
        if first_token is not None:
            timings["first_token_ms"] = first_token
        found: AgentState = {"draft": "".join(parts).strip(), "timings": timings}
        if model:
            found["llm_model"] = model
        return found

    async def converse(self, state: AgentState) -> AgentState:
        """A greeting or an off-topic question: a short answer without sources (D84)."""
        started = time.perf_counter()
        writer = get_stream_writer()
        question = state["question"]
        language = "ru" if CYRILLIC.search(question) else state.get("language", "en")
        route = "small_talk" if state.get("route") == "small_talk" else "general"
        sentences = SentenceFilter(hold=lambda s: bool(RU_DOSE.search(fold(s))))
        parts: list[str] = []
        messages = [SystemMessage(CONVERSE_PROMPT[language]), HumanMessage(question)]
        model: str | None = None
        async for chunk in self.llm.astream(messages):
            model = model_of(chunk) or model
            text = chunk.content if isinstance(chunk.content, str) else ""
            if not text:
                continue
            parts.append(text)
            for sentence in sentences.feed(text):
                writer({"type": "token", "text": sentence})
        for sentence in sentences.flush():
            writer({"type": "token", "text": sentence})
        timings = {**state.get("timings", {}), "answer_ms": _ms(started)}
        return {
            "draft": "".join(parts).strip(),
            "route": route,
            "reply_language": language,
            **({"llm_model": model} if model else {}),
            "sources": [],
            "timings": timings,
        }

    def _converse_safety(self, state: AgentState) -> AgentState:
        """Rules 1, 2 and 6 for an answer without sources: no dose, never "safe", never
        "non-toxic". Nothing to cite, so citations are dropped instead of checked."""
        violations: list[str] = []
        kept: list[str] = []
        for sentence in split_sentences(state.get("draft", "").replace(DISCLAIMER, "")):
            problems = sentence_problems(sentence)
            if RU_DOSE.search(fold(sentence)):
                problems.append("dose")
            if problems:
                violations += [p for p in problems if p not in violations]
                continue
            kept.append(re.sub(r"\s*\[\d+\]", "", sentence).strip())
        language = state.get("reply_language", state.get("language", "en"))
        body = " ".join(s for s in kept if s) or CONVERSE_FALLBACK.get(language, "")
        return {
            "answer": f"{body}\n\n{DISCLAIMER}",
            "safety": {
                "action": "rewritten" if violations else "ok",
                "violations": violations,
                "cited": [],
            },
            "sources": [],
            "agent": self._agent_report(state),
            "timings": {**state.get("timings", {}), "safety_ms": 0.0},
        }

    def _agent_report(self, state: AgentState) -> dict[str, Any]:
        rounds = state.get("round", 0)
        route = state.get("route", "documents")
        return {
            "planner": state.get("planner", "none"),
            "rounds": rounds,
            "refined": rounds > 1,
            "evidence": state.get("evidence", {}),
            "cache": False,
            # documents (cited answer), small_talk or general (no sources), D84
            "route": "documents" if route == "check" else route,
        }

    async def safety(self, state: AgentState) -> AgentState:
        started = time.perf_counter()
        if state.get("dose_question"):
            answer = f"{REFUSAL_DOSE}\n\n{DISCLAIMER}"
            report = {"action": "refused", "violations": ["dose_question"], "cited": []}
            return {
                "answer": answer,
                "safety": report,
                "sources": [],
                "tool_calls": [],
                "agent": {**self._agent_report(state), "planner": "none"},
            }
        if state.get("route") in ("small_talk", "general"):
            return self._converse_safety(state)
        found = any(
            pair.get("interactions")
            for entry in state.get("tool_results", [])
            if entry["name"] == "check_interaction" and entry["result"]
            for pair in entry["result"].get("pairs", [])
        )
        sources = state.get("sources", [])
        texts = [f"{s['title']} {s.get('text') or s.get('snippet', '')}" for s in sources]
        draft = strip_source_echo(state.get("draft", ""), sources)
        replaced = 0
        numbers = prediction_numbers(state)
        if numbers:  # a 3B model misreads the probabilities: the fixed summary replaces them
            kept = [s for s in split_sentences(draft) if not about_prediction(s, numbers)]
            replaced = len(split_sentences(draft)) - len(kept)
            draft = " ".join(kept)
        semantic = 0
        if self.attribution_threshold > 0 and draft and sources:
            try:
                draft, semantic = await attribute_by_meaning(
                    draft,
                    [t[:SOURCE_CHARS] for t in texts],
                    self.toolbox.retrievers.embedder,
                    threshold=self.attribution_threshold,
                )
            except EmbeddingError:
                semantic = 0  # the lexical attribution of check_answer still applies
        checked = check_answer(
            draft,
            len(sources),
            interaction_found=found,
            source_texts=texts,
        )
        checked.violations += ["citation_added_by_meaning"] * semantic
        checked.violations += ["toxicity_sentence_replaced"] * replaced
        summary, tox_cited = toxicity_summary(state)
        if summary:
            # Dose questions never get here; "refused" means no LLM sentence survived.
            refused = checked.action == "refused"
            body = "" if refused else checked.answer.rpartition(DISCLAIMER)[0].strip()
            checked.action = "rewritten" if refused or replaced else checked.action
            checked.answer = f"{body} {summary}".strip() + f"\n\n{DISCLAIMER}"
            checked.cited = sorted(set(checked.cited) | set(tox_cited))
        timings = {**state.get("timings", {}), "safety_ms": _ms(started)}
        return {
            "answer": checked.answer,
            "safety": {
                "action": checked.action,
                "violations": checked.violations,
                "cited": checked.cited,
            },
            "agent": self._agent_report(state),
            "timings": timings,
        }

    # ------------------------------------------------------------ running

    def _cacheable(self, state: AgentState) -> bool:
        return bool(state.get("answer")) and all(c.get("ok") for c in state.get("tool_calls", []))

    def _from_cache(self, state: AgentState, started: float) -> AgentState:
        state["agent"] = {**state.get("agent", {}), "cache": True}
        state["timings"] = {"cache_ms": _ms(started)}
        return state

    async def run(self, question: str, pills: list[int] | None = None) -> AgentState:
        started = time.perf_counter()
        key = self._cache_key(question, pills)
        cached = self.cache.get(key)
        if cached is not None:
            return self._from_cache(cached, started)
        state: AgentState = {"question": question, "pills": pills or []}
        result: AgentState = await self.graph.ainvoke(state)
        if self._cacheable(result):
            self.cache.put(key, result)
        return result

    async def stream(
        self, question: str, pills: list[int] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Events: {"type": "tool"}, {"type": "token"}, then one {"type": "final"}."""
        started = time.perf_counter()
        key = self._cache_key(question, pills)
        cached = self.cache.get(key)
        if cached is not None:
            final_state = self._from_cache(cached, started)
            body = final_state.get("answer", "").rpartition(DISCLAIMER)[0].strip()
            if body:
                yield {"type": "token", "text": body}
            yield {"type": "final", "state": final_state}
            return
        state: AgentState = {"question": question, "pills": pills or []}
        final: dict[str, Any] = dict(state)
        async for mode, payload in self.graph.astream(state, stream_mode=["custom", "updates"]):
            if mode == "custom":
                yield payload
            else:
                for update in payload.values():
                    if update:
                        final.update(update)
        if self._cacheable(final):  # type: ignore[arg-type]
            self.cache.put(key, final)  # type: ignore[arg-type]
        yield {"type": "final", "state": final}


def model_of(chunk: Any) -> str | None:
    """The model that wrote a streamed chunk (Groq: model_name, Ollama: model), if it says."""
    metadata = getattr(chunk, "response_metadata", None) or {}
    name = metadata.get("model_name") or metadata.get("model")
    return str(name) if name else None


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def tool_message_json(result: Any) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)[:4000]


__all__ = [
    "AIMessage",
    "AgentState",
    "AnswerCache",
    "TujyaAgent",
    "detect_intents",
    "detect_language",
]
