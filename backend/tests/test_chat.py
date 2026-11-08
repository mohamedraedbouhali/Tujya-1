"""POST /api/chat and the agentic LangGraph agent, with a scripted LLM, fake embeddings and
a real ChromaDB index in a temporary folder."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.medicines import DISCLAIMER
from app.rag.agent import LITERATURE, AnswerCache, detect_intents, strip_source_echo
from app.rag.embeddings import FakeEmbedder, fold
from app.rag.runtime import AgentHolder
from tests.conftest import USER, sign_in
from tests.rag_fakes import DIM, FakeChatModel, build_index


def use_agent(app: FastAPI, llm: FakeChatModel, **settings: Any) -> None:
    """A fresh agent for this app, with some settings changed for the test."""
    app.state.agents = AgentHolder(
        app.state.settings.model_copy(update=settings),
        app.state.pharma_engine,
        llm=llm,
        embedder=FakeEmbedder(DIM),
    )


@pytest.fixture
def llm() -> FakeChatModel:
    return FakeChatModel(prompts=[])


@pytest.fixture
def chat_app(app: FastAPI, pharma: str, llm: FakeChatModel) -> FastAPI:
    asyncio.run(build_index(app.state.settings.chroma_path))
    use_agent(app, llm)
    return app


@pytest.fixture
def client(chat_app: FastAPI, browser: Callable[[], TestClient]) -> TestClient:
    return sign_in(browser(), USER)


def ask(client: TestClient, question: str, **extra: object) -> dict:
    response = client.post("/api/chat", json={"question": question, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def events(response: Any) -> list[tuple[str, dict]]:
    found = []
    for block in response.text.strip().split("\n\n"):
        name = block.split("\n")[0].removeprefix("event: ")
        found.append((name, json.loads(block.split("\n")[1].removeprefix("data: "))))
    return found


def test_chat_needs_sign_in(chat_app: FastAPI, anonymous: TestClient) -> None:
    assert anonymous.post("/api/chat", json={"question": "warfarine ?"}).status_code == 401


def test_fast_path_plans_by_rules_without_a_planner_call(
    client: TestClient, llm: FakeChatModel
) -> None:
    llm.answer = (
        "Le fluconazole augmente le temps de prothrombine chez les patients sous warfarine [2]. "
        "DDInter classe cette interaction comme majeure [1]."
    )
    body = ask(client, "La warfarine et le fluconazole interagissent-ils ?")
    assert body["language"] == "fr"
    assert body["ingredients"] == ["warfarin", "fluconazole"]
    calls = [(c["name"], c["chosen_by"], c["round"]) for c in body["tool_calls"]]
    assert calls == [("check_interaction", "rule", 1), ("search_documents", "rule", 1)]
    assert llm.kinds() == ["answer"]  # one model call: the answer
    assert body["agent"]["planner"] == "rules" and body["agent"]["rounds"] == 1
    assert body["agent"]["evidence"]["enough"] and not body["agent"]["cache"]
    first = body["citations"][0]
    assert first["n"] == 1 and first["doc_type"] == "interaction" and "Major" in first["title"]
    assert {c["n"] for c in body["citations"] if c["cited"]} == {1, 2}
    assert all(c["url"] and c["title"] for c in body["citations"])
    assert "retracted" not in json.dumps(body["citations"]).lower()
    assert body["answer"].endswith(DISCLAIMER) and body["safety"]["action"] == "ok"
    assert body["model"] == "fake-llm" and body["timings"]["total_ms"] > 0
    # The answer prompt holds the numbered sources and the rules.
    system, user = llm.prompts[-1]
    assert "JAMAIS de dose" in str(system.content) and "[1] DDInter 2.0" in str(user.content)


def test_llm_planner_mode_keeps_the_rule_minimum(
    chat_app: FastAPI, client: TestClient, llm: FakeChatModel
) -> None:
    use_agent(chat_app, llm, agent_planner="llm")
    llm.tool_calls = [
        {"name": "search_documents", "args": {"query": "fluconazole warfarin interaction"}},
        {"name": "not_a_tool", "args": {}},  # ignored
    ]
    body = ask(client, "La warfarine et le fluconazole interagissent-ils ?")
    names = [(c["name"], c["chosen_by"]) for c in body["tool_calls"]]
    assert ("search_documents", "llm") in names and ("check_interaction", "rule") in names
    assert all(c["ok"] for c in body["tool_calls"])
    assert llm.kinds() == ["planner", "answer"] and body["agent"]["planner"] == "llm"


def test_question_without_a_known_drug_is_planned_by_the_llm(
    client: TestClient, llm: FakeChatModel
) -> None:
    llm.tool_calls = [{"name": "search_documents", "args": {"query": "dizziness"}}]
    llm.answer = "Des vertiges sont décrits [1]."
    body = ask(client, "Quels médicaments donnent des vertiges ?")
    assert body["ingredients"] == [] and llm.kinds()[0] == "planner"
    assert body["agent"]["planner"] == "llm"
    assert [(c["name"], c["chosen_by"]) for c in body["tool_calls"]] == [
        ("search_documents", "llm")
    ]


def test_unsafe_answer_is_rewritten(client: TestClient, llm: FakeChatModel) -> None:
    llm.answer = (
        "Le losartan peut donner des vertiges [1]. Prenez 50 mg le matin [1]. "
        "Cette association est sans danger. Voir aussi [12]."
    )
    body = ask(client, "Effets indésirables du losartan ?")
    answer = body["answer"]
    assert "50 mg" not in answer and "sans danger" not in answer and "[12]" not in answer
    assert set(body["safety"]["violations"]) >= {"dose", "safe", "bad_citation"}
    assert body["safety"]["action"] == "rewritten" and answer.endswith(DISCLAIMER)
    # The topic (side effects) made the rules fetch that label section first.
    info = next(c for c in body["tool_calls"] if c["name"] == "get_drug_info")
    assert info["args"] == {"drug": "losartan", "sections": ["adverse_reactions"]}


def test_dose_question_is_refused_without_calling_the_llm(
    client: TestClient, llm: FakeChatModel
) -> None:
    body = ask(client, "Quelle dose de warfarine dois-je prendre ?")
    assert body["safety"]["action"] == "refused" and "dose_question" in body["safety"]["violations"]
    assert "jamais de dose" in body["answer"] and body["answer"].endswith(DISCLAIMER)
    assert body["tool_calls"] == [] and body["citations"] == [] and llm.prompts == []


def test_planner_failure_falls_back_to_rules(
    chat_app: FastAPI, client: TestClient, llm: FakeChatModel
) -> None:
    use_agent(chat_app, llm, agent_planner="llm")
    llm.fail_planner = True
    llm.answer = "Le losartan peut donner des vertiges [1]."
    body = ask(client, "What are the adverse reactions of losartan?", pills=[5])
    assert body["language"] == "en"
    assert {c["name"] for c in body["tool_calls"]} == {"check_interaction", "search_documents"}
    assert {"losartan", "hydrochlorothiazide"} <= set(body["ingredients"])  # from pill 5
    assert body["citations"] and body["answer"].endswith(DISCLAIMER)
    assert body["agent"]["planner"] == "rules (planner failed)"


def test_weak_evidence_makes_the_agent_search_again(
    chat_app: FastAPI, client: TestClient, llm: FakeChatModel
) -> None:
    use_agent(chat_app, llm, rag_min_similarity=0.99)  # no fake hit is that similar
    llm.refine_calls = [
        {
            "name": "search_documents",
            "args": {
                "query": "losartan adverse reactions",
                "ingredients": ["losartan"],
                "sections": ["adverse_reactions"],
            },
        }
    ]
    llm.answer = "Le losartan peut donner des vertiges [1]."
    body = ask(client, "Effets indésirables du losartan ?")
    assert llm.kinds() == ["refine", "answer"]
    second = [c for c in body["tool_calls"] if c["round"] == 2]
    assert [(c["name"], c["chosen_by"]) for c in second] == [("search_documents", "llm")]
    assert body["agent"]["rounds"] == 2 and body["agent"]["refined"]
    assert any("weak search matches" in m for m in body["agent"]["evidence"]["missing"])
    # The agent saw what was searched, what was found and what is missing.
    refine_prompt = str(llm.prompts[0][1].content)
    assert "Calls already made" in refine_prompt and "Missing: weak search matches" in refine_prompt
    assert body["answer"].endswith(DISCLAIMER)


def test_rules_rewrite_the_search_when_the_agent_proposes_nothing(
    chat_app: FastAPI, client: TestClient, llm: FakeChatModel
) -> None:
    use_agent(chat_app, llm, rag_min_similarity=0.99)
    body = ask(client, "Effets indésirables du losartan ?")
    second = [c for c in body["tool_calls"] if c["round"] == 2]
    assert [(c["name"], c["chosen_by"]) for c in second] == [("search_documents", "rule")]
    assert second[0]["args"] == {
        "query": "losartan adverse reactions side effects",
        "ingredients": ["losartan"],
        "sections": ["adverse_reactions"],
    }


def test_one_round_never_refines(chat_app: FastAPI, client: TestClient, llm: FakeChatModel) -> None:
    use_agent(chat_app, llm, rag_min_similarity=0.99, agent_max_rounds=1)
    body = ask(client, "Effets indésirables du losartan ?")
    assert llm.kinds() == ["answer"] and body["agent"]["rounds"] == 1
    assert not body["agent"]["evidence"]["enough"]


def test_same_question_is_answered_from_the_cache(client: TestClient, llm: FakeChatModel) -> None:
    first = ask(client, "Effets indésirables du losartan ?")
    calls = len(llm.prompts)
    again = ask(client, "  effets INDÉSIRABLES du losartan ? ")  # same once normalised
    assert len(llm.prompts) == calls and again["agent"]["cache"]
    assert again["answer"] == first["answer"] and again["citations"] == first["citations"]
    other = ask(client, "Effets indésirables du losartan ?", pills=[5])  # other pills
    assert not other["agent"]["cache"] and len(llm.prompts) > calls


def test_stream_sends_tools_tokens_then_final(client: TestClient, llm: FakeChatModel) -> None:
    llm.answer = "Le fluconazole est sûr. Il augmente le temps de prothrombine [1]."
    response = client.post(
        "/api/chat", json={"question": "fluconazole et warfarine ?", "stream": True}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    found = events(response)
    kinds = [name for name, _ in found]
    assert kinds[0] == "tool" and kinds[-1] == "final" and "token" in kinds
    streamed = "".join(d["text"] for name, d in found if name == "token")
    assert "sûr" not in streamed and "prothrombine" in streamed  # held back while streaming
    final = found[-1][1]
    assert "sûr" not in final["answer"] and final["answer"].endswith(DISCLAIMER)
    # The same question streamed again comes from the cache: the answer, then final.
    cached = events(
        client.post("/api/chat", json={"question": "fluconazole et warfarine ?", "stream": True})
    )
    assert [name for name, _ in cached] == ["token", "final"]
    assert cached[-1][1]["agent"]["cache"] and cached[-1][1]["answer"] == final["answer"]


def test_no_index_answers_503(app: FastAPI, pharma: str, browser: Callable[[], TestClient]) -> None:
    use_agent(app, FakeChatModel())
    response = sign_in(browser(), USER).post("/api/chat", json={"question": "warfarine ?"})
    assert response.status_code == 503 and "app.rag.index" in response.json()["detail"]


def test_chat_route_in_openapi(chat_app: FastAPI, anonymous: TestClient) -> None:
    paths = anonymous.get("/openapi.json").json()["paths"]
    assert "/api/chat" in paths and "post" in paths["/api/chat"]


def test_topics_of_a_question() -> None:
    assert detect_intents("Quelles sont les contre-indications de la metformine ?") == [
        "contraindications"
    ]
    assert detect_intents("Can I take warfarin while pregnant?") == ["pregnancy"]
    assert detect_intents("What is the boxed warning of citalopram?") == ["boxed_warning"]
    assert {"adverse_reactions", "geriatric"} <= set(
        detect_intents("Effets secondaires chez les personnes âgées ?")
    )
    assert detect_intents("Indications du losartan ?") == ["indications"]
    assert LITERATURE.search(fold("Que disent les études sur la warfarine ?"))
    assert not LITERATURE.search(fold("Effets indésirables du losartan ?"))


def test_an_echoed_source_header_is_removed(client: TestClient, llm: FakeChatModel) -> None:
    # What qwen2.5:3b did on two real questions: citation numbers, then a source's header.
    llm.answer = (
        "[1] [2] Losartan label (Cozaar): Adverse reactions (openFDA drug label, 20240101) "
        "Dizziness was the most common adverse reaction [1]."
    )
    body = ask(client, "Effets indésirables du losartan ?")
    assert body["answer"].startswith("Dizziness was the most common adverse reaction [1].")
    assert body["answer"].endswith(DISCLAIMER)


def test_strip_source_echo_keeps_normal_answers() -> None:
    sources = [{"title": "DDInter 2.0: a + b (Major)", "source_name": "DDInter 2.0"}]
    normal = "DDInter 2.0 lists a Major interaction [1]."
    assert strip_source_echo(normal, sources) == normal
    assert strip_source_echo("[1] [2] [6] Warfarin interacts [1].", sources) == (
        "Warfarin interacts [1]."
    )


def test_answer_cache_expires_and_evicts() -> None:
    cache = AnswerCache(size=2, seconds=60)
    cache.put(("a",), {"answer": "A"})
    cache.put(("b",), {"answer": "B"})
    assert cache.get(("a",)) == {"answer": "A"}  # "a" is now the most recent
    cache.put(("c",), {"answer": "C"})
    assert cache.get(("b",)) is None and cache.get(("c",)) == {"answer": "C"}
    stored = cache.get(("a",))
    assert stored is not None
    stored["answer"] = "changed"  # callers get copies
    assert cache.get(("a",)) == {"answer": "A"}
    expired = AnswerCache(size=2, seconds=0)
    expired.put(("a",), {"answer": "A"})
    assert expired.get(("a",)) is None
