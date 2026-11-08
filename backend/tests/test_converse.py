"""Greetings and off-topic questions (D84): a short answer without sources, never for a
medical question. Scripted LLM, fake embeddings, real ChromaDB index (as in test_chat.py)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.medicines import DISCLAIMER
from app.rag.agent import detect_language, route_of
from tests.conftest import USER, sign_in
from tests.rag_fakes import FakeChatModel, build_index
from tests.test_chat import ask, use_agent


@pytest.fixture
def llm() -> FakeChatModel:
    return FakeChatModel(prompts=[], answer="Napoleon was a French emperor.")


@pytest.fixture
def chat_app(app: FastAPI, pharma: str, llm: FakeChatModel) -> FastAPI:
    asyncio.run(build_index(app.state.settings.chroma_path))
    # Above every fake similarity: whatever is not medical counts as off topic here.
    use_agent(app, llm, rag_topic_similarity=0.99)
    return app


@pytest.fixture
def client(chat_app: FastAPI, browser: Callable[[], TestClient]) -> TestClient:
    return sign_in(browser(), USER)


def system_prompt(llm: FakeChatModel) -> str:
    return str(llm.prompts[-1][0].content)


def test_a_greeting_is_answered_without_searching(client: TestClient, llm: FakeChatModel) -> None:
    llm.answer = "Hello! I can identify pills and check drug interactions."
    body = ask(client, "hi")
    assert body["agent"]["route"] == "small_talk"
    assert body["tool_calls"] == [] and body["citations"] == []
    assert llm.kinds() == ["answer"]  # one model call, no planner
    assert system_prompt(llm).startswith("You are Tujya, a friendly assistant")
    assert body["answer"] == f"{llm.answer}\n\n{DISCLAIMER}"
    assert body["safety"]["action"] == "ok"

    ask(client, "bonjour")
    assert "Réponds en français" in system_prompt(llm)


def test_an_off_topic_question_gets_a_general_answer(
    client: TestClient, llm: FakeChatModel
) -> None:
    body = ask(client, "Who was Napoleon?")
    assert body["agent"]["route"] == "general"
    # Searched once by rule (no planner call): nothing close, so no sources are shown.
    assert [(c["name"], c["chosen_by"]) for c in body["tool_calls"]] == [
        ("search_documents", "rule")
    ]
    assert body["citations"] == [] and llm.kinds() == ["answer"]
    assert body["answer"].startswith("Napoleon was a French emperor.")


def test_a_question_close_to_the_documents_gets_the_cited_answer(
    chat_app: FastAPI, client: TestClient, llm: FakeChatModel
) -> None:
    use_agent(chat_app, llm, rag_topic_similarity=0.01)
    llm.answer = "Des vertiges sont décrits [1]."
    body = ask(client, "Who was Napoleon?")
    assert body["agent"]["route"] == "documents"
    assert body["citations"] and llm.kinds() == ["answer"]
    assert "Answer ONLY from the numbered sources" in system_prompt(llm)


def test_zero_disables_the_check(chat_app: FastAPI, client: TestClient, llm: FakeChatModel) -> None:
    use_agent(chat_app, llm, rag_topic_similarity=0.0)
    assert ask(client, "Who was Napoleon?")["agent"]["route"] == "documents"


@pytest.mark.parametrize(
    "question",
    [
        "What are the side effects of my medicine?",
        "Quels médicaments donnent des vertiges ?",
        "Is it dangerous to drink alcohol with antidepressants?",
        "warfarine ?",
    ],
)
def test_a_medical_question_never_gets_a_general_answer(
    client: TestClient, llm: FakeChatModel, question: str
) -> None:
    llm.answer = "Des vertiges sont décrits [1]."
    assert ask(client, question)["agent"]["route"] == "documents"


def test_a_follow_up_about_the_confirmed_pills_stays_with_the_documents(
    client: TestClient, llm: FakeChatModel
) -> None:
    llm.answer = "DDInter classe cette interaction comme majeure [1]."
    for question in ["and together?", "pourquoi ?", "can I have them with coffee?"]:
        assert ask(client, question, pills=[5, 7])["agent"]["route"] == "documents"


def test_an_off_topic_word_next_to_confirmed_pills_gets_a_general_answer(
    client: TestClient, llm: FakeChatModel
) -> None:
    llm.answer = "Donald Trump is an American businessman and politician."
    body = ask(client, "trump", pills=[5, 7])
    assert body["agent"]["route"] == "general"
    assert body["citations"] == [] and body["answer"].startswith("Donald Trump")


def test_a_general_answer_keeps_the_no_dose_rule(client: TestClient, llm: FakeChatModel) -> None:
    llm.answer = "Napoleon was a French emperor. Take 500 mg of aspirin for headaches."
    body = ask(client, "Who was Napoleon?")
    assert body["answer"] == f"Napoleon was a French emperor.\n\n{DISCLAIMER}"
    assert body["safety"]["action"] == "rewritten" and "dose" in body["safety"]["violations"]

    llm.answer = "Наполеон был императором Франции. Принимайте 2 таблетки в день."
    body = ask(client, "Кто такой Наполеон?")
    assert "Отвечай по-русски" in system_prompt(llm)
    assert body["answer"] == f"Наполеон был императором Франции.\n\n{DISCLAIMER}"


def test_routes_and_language_of_short_messages() -> None:
    def route(question: str, pills: list[int] | None = None) -> str:
        return route_of(question, asked=[], pills=pills or [], check=True)

    assert route("hi") == route("Merci beaucoup !") == route("привет") == "small_talk"
    assert route("who are you?") == "small_talk"
    assert route("help me with my headache") == "documents"  # a medical word wins
    assert route("who won the world cup?") == "check"
    assert route("who won the world cup?", pills=[5]) == route("trump", pills=[5]) == "check"
    assert route("and together?", pills=[5]) == route("c'est grave ?", pills=[5]) == "documents"
    assert route("and together?") == "check"  # no pills: nothing to point back at
    assert route_of("who won?", asked=[], pills=[], check=False) == "documents"
    assert detect_language("bonjour") == detect_language("qui est Ronaldo ?") == "fr"
    assert detect_language("hi") == detect_language("who is Ronaldo?") == "en"
