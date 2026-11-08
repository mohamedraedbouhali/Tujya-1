"""Which model answers (D86): local Ollama by default, Groq with a key, Ollama as fallback.
No network: the models are only built, or replaced by scripted fakes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables.fallbacks import RunnableWithFallbacks
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from pydantic import SecretStr

from app.config import Settings
from app.rag.agent import model_of
from app.rag.embeddings import FakeEmbedder
from app.rag.runtime import AgentHolder, make_llm
from tests.conftest import USER, sign_in
from tests.rag_fakes import DIM, FakeChatModel, build_index
from tests.test_chat import ask

KEY = "gsk_test_not_a_real_key"


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_ollama_answers_by_default_and_without_a_key() -> None:
    assert isinstance(make_llm(settings()), ChatOllama)
    assert isinstance(make_llm(settings(llm_provider="groq")), ChatOllama)


def test_groq_answers_with_the_local_model_as_fallback() -> None:
    llm = make_llm(settings(llm_provider="groq", groq_api_key=KEY))
    assert isinstance(llm, RunnableWithFallbacks)
    assert isinstance(llm.runnable, ChatGroq) and isinstance(llm.fallbacks[0], ChatOllama)
    assert llm.runnable.model_name == "qwen/qwen3.8-27b"
    assert llm.runnable.max_retries == 0  # a rate limit falls back at once
    # Tool calling (the planner) goes to both models.
    assert isinstance(llm.bind_tools([]), RunnableWithFallbacks)


def test_the_key_never_shows_in_settings() -> None:
    configured = settings(llm_provider="groq", groq_api_key=KEY)
    assert isinstance(configured.groq_api_key, SecretStr)
    assert KEY not in repr(configured) and KEY not in str(configured.model_dump())


def test_model_of_a_chunk() -> None:
    assert model_of(AIMessageChunk(content="", response_metadata={"model_name": "qwen/x"})) == (
        "qwen/x"
    )
    assert model_of(AIMessageChunk(content="", response_metadata={"model": "qwen2.5:3b"})) == (
        "qwen2.5:3b"
    )
    assert model_of(AIMessageChunk(content="hi")) is None


class RateLimited(FakeChatModel):
    """A hosted model that refuses every call, like Groq over its rate limit."""

    async def _astream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        raise RuntimeError("429 rate limit")
        yield  # pragma: no cover  (makes this an async generator)


@pytest.fixture
def client(app: FastAPI, pharma: str, browser: Callable[[], TestClient]) -> TestClient:
    asyncio.run(build_index(app.state.settings.chroma_path))
    return sign_in(browser(), USER)


def test_a_failing_hosted_model_falls_back_to_the_local_one(
    app: FastAPI, client: TestClient
) -> None:
    local = FakeChatModel(prompts=[], answer="DDInter classe cette interaction comme majeure [1].")
    app.state.agents = AgentHolder(
        app.state.settings,
        app.state.pharma_engine,
        llm=RateLimited(prompts=[]).with_fallbacks([local]),
        embedder=FakeEmbedder(DIM),
    )
    body = ask(client, "La warfarine et le fluconazole interagissent-ils ?")
    assert body["answer"].startswith("DDInter classe cette interaction comme majeure [1].")
    assert local.kinds() == ["answer"]
