# Tujya agent (LangGraph) and POST /api/chat

The agent answers questions about the confirmed pills and their active ingredients, only
from retrieved documents and tool results, with numbered citations. Code:
`backend/app/rag/` (agent.py, tools.py, safety.py, names.py, runtime.py), route
`backend/app/routers/chat.py`. Corpus and retrieval: docs/RAG.md. Decisions D57-D59, D63,
and since 2026-11-01 D76 (ChromaDB), D77 (agentic loop), D78 (speed).

## Graph: agentic RAG (D77)

```
START -> understand --(dose question)-------------------------------------> safety -> END
             \--> plan -> act -> grade --(evidence enough, or last round)--> answer -> safety -> END
                           ^        \--(evidence weak)--> refine --\
                           \--------------------------------------/
```

| Node | What it does | LLM |
|---|---|---|
| `understand` | drug names in the question (French or English: "warfarine" -> warfarin, "paracétamol" -> acetaminophen) and the confirmed pills' ingredients; the **topic** (contraindications, side effects, boxed warning, mechanism, warnings, pregnancy, breastfeeding, children, older patients, indications) and whether it asks for **studies**; language (fr / en); dose question? | no |
| `plan` | the first tool calls. **Fast path** (`auto`, default): when the question names known drugs, rules choose them with no LLM call: `check_interaction` for two or more drugs, `get_drug_info` with the topic's label sections for the drug asked about, `predict_toxicity` for a toxicity question, `search_documents` always (PubMed only when studies are asked for). Otherwise (no known drug, or `agent_planner=llm`) the LLM plans by tool calling and the graph adds what the question always needs | only off the fast path |
| `act` | runs the planned calls **concurrently**, never the same call twice, and records each one (`chosen_by`: `llm` or `rule`; `round`) | no |
| `grade` | numbered sources [1], [2] ... (DDInter first, then toxicity predictions, label excerpts, search hits; the latest round first; at most 8) and the **evidence check**, by rules: a source about every drug asked about (when the corpus has one), the label section of the topic, a PubMed abstract when studies are asked for, and a best dense hit with cosine similarity of at least `rag_min_similarity` | no |
| `refine` | only when the evidence is weak and rounds remain: the **LLM agent** gets the question, the calls already made, the sources found and what is missing, and chooses new calls (an English query, sections or document types, another tool). If it proposes nothing new, rules rewrite the search (English drug names + topic words, the topic's sections). Then `act` and `grade` again | yes |
| `answer` | the LLM answers from the numbered sources only, with the rules in the system prompt (French or English); streamed sentence by sentence through the safety filter | yes |
| `safety` | the rules below on the whole answer: rewrite, or refuse | no |

If a planner or refinement call fails (model down, bad JSON), the rule-based calls still
run. `agent_max_rounds` (default 2) bounds the loop: the first retrieval round plus at most
one refinement. The response's `agent` field says what happened: `planner` (`rules`, `llm`,
`rules (planner failed)`), `rounds`, `refined`, the `evidence` check (`enough`, `missing`,
`best_similarity`) and `cache`.

## Speed (D78)

| Measure | Saves |
|---|---|
| Fast path: no planner call when the question names known drugs (most questions) | one LLM call |
| Tool calls run concurrently | the slower tool instead of the sum |
| Query embeddings cached (512 queries); label sections indexed by (ingredient, section) | an embedding call; a scan of every chunk |
| Grade by rules, not by an LLM judge; refinement only when the evidence is weak | an LLM call on most questions |
| Answer cache: the same question with the same pills (case, accents and spaces ignored) gets the checked answer again, with no model call, until the index changes or after an hour | the whole pipeline |
| Warm-up at start: chunk index, bge-m3 and the LLM loaded before the first question; `keep_alive` 1 h keeps both models in GPU memory | 10-20 s on the first question |

Measured times: docs/BENCHMARK.md, section "ChromaDB and the agentic graph".

## Tools (`app/rag/tools.py`, shared with the MCP server)

| Tool | Arguments | Returns |
|---|---|---|
| `identify_pills` | `image_path` or `image_base64` | the `/api/scan` result: boxes, top-5, `needs_confirmation` (not given to the chat LLM: a chat question has no image; MCP clients have it) |
| `check_interaction` | `drugs` (names, French or English), `pills` (class_ids) | the `/api/interactions` result: every pair, DDInter severity, description, source; "aucune interaction connue dans cette base de données" when nothing is listed |
| `get_drug_info` | `drug`, optional `sections` | pill classes containing the ingredient, and the first chunk of each label section (boxed warning, indications, contraindications, warnings, interactions, mechanism) |
| `search_documents` | `query`, `ingredients`, `doc_types`, `sections`, `k`, `exclude_retracted` | hybrid search hits with title, section, URL, source, date, licence, text |
| `predict_toxicity` (bonus) | `molecules` (1 or 2 names or SMILES) | Tox21 in vitro assay probabilities per molecule, never about a mixture (docs/TOXICITY.md); added by rule to a toxicity question; its sentences in the answer are written by the code, not the LLM (D74) |

**Extension point.** A tool is one async method on `Toolbox` and one entry in
`TOOL_SPECS`; it is then available to the agent (`CHAT_TOOLS`) and the MCP server. Two
bonus tools were planned: `predict_toxicity` is implemented (session 4, docs/TOXICITY.md);
`predict_synergy(drug_a, drug_b)` (cancer synergy from the DrugComb data already in the
pipeline) is not.

## Safety rules (`app/rag/safety.py`, D63)

Applied to every answer, sentence by sentence:

1. **No dose.** A question asking for a dose ("quelle dose", "posologie", "how much") is
   refused before any LLM call. A sentence with an amount of medicine ("50 mg", "2
   comprimés", "deux fois par jour", "mg/kg") is removed; lab values ("eGFR 30 mL/min",
   "200 mg/dL") are not doses.
2. **Never "safe".** A sentence with "sûr", "sans danger", "sans risque", "safe" is removed;
   if no interaction was found, "Aucune interaction connue dans cette base de données." is
   written instead.
3. **No invented timing advice.** A sentence about spacing or meals ("2 heures
   d'intervalle", "avant le repas", "hours apart") is kept only if it cites a source.
4. **Citations.** `[n]` must point to a numbered source (others are removed). A sentence the
   model forgot to cite gets the source containing at least 60 % of its content words (it
   is then really in that source); an answer that still cites nothing gets "Sources
   consultées : [1] ...". No source at all: the answer says so and does not answer.
   Label cross-references ("[see Contraindications (4)]") are removed from the sources
   given to the model and from the answer.
5. **Disclaimer.** Every answer ends with "Information uniquement, consultez un pharmacien
   ou un médecin."

While streaming, a sentence that breaks rules 1-3 is held back, so it never reaches the
screen; the `final` event carries the checked answer, which the app displays.

## POST /api/chat

Signed-in users only. Body:

```json
{"question": "La warfarine interagit-elle avec le fluconazole ?", "pills": [9], "stream": false}
```

Response (`ChatResult`): `answer` (checked, ends with the disclaimer), `language`,
`ingredients`, `citations` (n, title, url, section, snippet, source_name, doc_type, date,
`cited`), `tool_calls` (name, args, chosen_by, ok, summary, round), `safety` (action `ok` /
`rewritten` / `refused`, violations, cited numbers), `agent` (planner, rounds, refined,
evidence, cache), `model`, `timings` (per node, `first_token_ms`, and total), `disclaimer`.

With `"stream": true` the answer is Server-Sent Events: `tool` (each call, as it happens),
`token` (answer text, one checked sentence at a time), then `final` (the `ChatResult`) or
`error`. nginx passes the stream through unbuffered (`X-Accel-Buffering: no`).

Errors: 401 not signed in; 503 when the index is empty ("run `python -m app.rag.index`"),
when ChromaDB or Ollama is not reachable.

Configuration (`SYNERGYRX_*`): `OLLAMA_URL` (compose: `http://ollama:11434`), `LLM_MODEL`
(`qwen2.5:3b`), `LLM_TEMPERATURE` (0.1), `LLM_NUM_CTX` (4096, D68), `LLM_MAX_TOKENS` (450), `EMBEDDING_MODEL`
(`bge-m3`), `RAG_TOP_K` (6), `CHROMA_URL` (compose: `http://chroma:8000`) or `CHROMA_PATH`
(default `data/rag/chroma`), `AGENT_PLANNER` (`auto`, `llm` or `rules`), `AGENT_MAX_ROUNDS`
(2), `RAG_MIN_SIMILARITY` (evidence check, docs/BENCHMARK.md), `ANSWER_CACHE_SIZE` (256, 0
disables it), `ANSWER_CACHE_SECONDS` (3600), `LLM_KEEP_ALIVE` (`1h`), `RAG_WARMUP` (true).

From the command line: `python scripts/ask.py "question" [--pills 9 120]` (backend venv).

## Example (real models, 2026-10-28)

`What are the contraindications of metformin?` -> planner: `get_drug_info` and
`search_documents`; answer: "Metformin hydrochloride tablets are contraindicated in
patients with severe renal impairment (eGFR below 30 mL/min/1.73 m²), hypersensitivity to
metformin, and acute or chronic metabolic acidosis, including diabetic ketoacidosis with or
without coma [1]." + disclaimer; about 15 s in total on the RTX 2050 (planner ~7 s,
answer ~6 s).

## Tests (no Ollama, no real embeddings)

`backend/tests/test_chat.py`: a scripted chat model (`tests/rag_fakes.py`: planner calls,
refinement calls and streamed answers) and hashed fake embeddings over a six-chunk corpus in
a real ChromaDB collection. Covers sign-in, the fast path (one model call: the answer), the
LLM planner mode with the rule minimum, a question without a known drug planned by the LLM,
unknown tools ignored, citations mapping, retracted excluded, unsafe answers rewritten
(dose, "sans danger", bad citation), dose question refused without any LLM call, planner
failure fallback, pills -> ingredients, **weak evidence -> a second round chosen by the LLM
agent**, the rule rewrite when the agent proposes nothing, one round never refining, the
answer cache (normalised question, other pills not cached, expiry and eviction), topic
detection, SSE order (tool, token, final) with unsafe sentences held back and a cached
stream, 503 without index. `backend/tests/test_safety.py`: the rules and the name matcher.
