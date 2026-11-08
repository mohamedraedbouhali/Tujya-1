"""Offline stand-ins for the RAG tests: a scripted chat model and a tiny corpus.

CI never runs Ollama or a real embedding model: `FakeEmbedder` (app/rag/embeddings.py)
hashes words, and `FakeChatModel` returns scripted tool calls and answers. The index is a
real ChromaDB collection in a temporary folder.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from app.rag.embeddings import FakeEmbedder
from app.rag.index import index_chunks
from app.rag.store import ChromaStore, make_client

DIM = 64


def _calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**c, "id": f"call_{i}", "type": "tool_call"} for i, c in enumerate(calls)]


class FakeChatModel(BaseChatModel):
    """Planner calls (system prompt "You are the tool planner") get `tool_calls`, refinement
    calls ("You are the retrieval agent") get `refine_calls`; answer calls get `answer`,
    streamed word by word. Every prompt is kept in `prompts`."""

    model: str = "fake-llm"
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    refine_calls: list[dict[str, Any]] = Field(default_factory=list)
    answer: str = "Le fluconazole augmente l'effet de la warfarine [1]."
    fail_planner: bool = False
    prompts: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-chat"

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatModel:  # type: ignore[override]
        return self

    def kinds(self) -> list[str]:
        """planner / refine / answer, one per prompt received, in order."""
        found = []
        for messages in self.prompts:
            system = str(messages[0].content)
            if system.startswith("You are the tool planner"):
                found.append("planner")
            elif system.startswith("You are the retrieval agent"):
                found.append("refine")
            else:
                found.append("answer")
        return found

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        self.prompts.append(messages)
        system = str(messages[0].content)
        if system.startswith("You are the tool planner"):
            if self.fail_planner:
                raise RuntimeError("planner down")
            return AIMessage(content="", tool_calls=_calls(self.tool_calls))
        if system.startswith("You are the retrieval agent"):
            return AIMessage(content="", tool_calls=_calls(self.refine_calls))
        return AIMessage(content=self.answer)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text = str(self._reply(messages).content)
        for word in text.split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + " "))

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._stream(messages, stop):
            yield chunk


def _chunk(chunk_id: str, doc_type: str, ingredients: list[str], section: str, title: str,
           text: str, **extra: Any) -> dict[str, Any]:  # fmt: skip
    return {
        "chunk_id": chunk_id,
        "doc_id": f"doc:{chunk_id}",
        "doc_type": doc_type,
        "ingredients": ingredients,
        "mentioned_ingredients": extra.pop("mentioned", []),
        "section": section,
        "chunk_index": 0,
        "title": title,
        "text": text,
        "source_name": extra.pop("source_name", "openFDA drug label"),
        "url": extra.pop("url", f"https://example.org/{chunk_id}"),
        "date": "20240101",
        "version": "v1",
        "license": "CC0",
        "article_type": extra.pop("article_type", None),
        "is_retracted": extra.pop("is_retracted", False),
        "language": "en",
    }


CORPUS = [
    _chunk(
        "flu-di",
        "label",
        ["fluconazole"],
        "drug_interactions",
        "Fluconazole label (Diflucan): Drug interactions",
        "Fluconazole increases the prothrombin time in patients taking warfarin. "
        "Careful monitoring of prothrombin time is recommended.",
        mentioned=["warfarin"],
    ),
    _chunk(
        "war-ci",
        "label",
        ["warfarin"],
        "contraindications",
        "Warfarin label (Coumadin): Contraindications",
        "Warfarin is contraindicated in pregnancy except in women with mechanical heart valves.",
    ),
    _chunk(
        "los-aw",
        "label",
        ["losartan"],
        "adverse_reactions",
        "Losartan label (Cozaar): Adverse reactions",
        "Dizziness and upper respiratory infection were the most common adverse reactions.",
    ),
    _chunk(
        "pm-retracted",
        "abstract",
        ["warfarin"],
        "results",
        "A retracted warfarin study",
        "Warfarin bleeding risk doubled with fluconazole in this cohort.",
        source_name="PubMed (J Test)",
        article_type="research",
        is_retracted=True,
    ),
    _chunk(
        "pm-ok",
        "abstract",
        ["warfarin"],
        "conclusions",
        "Azole antifungals and warfarin",
        "Azole antifungals inhibit CYP2C9 and raise warfarin exposure and bleeding risk.",
        source_name="PubMed (J Test)",
        article_type="review",
        mentioned=["fluconazole"],
    ),
    _chunk(
        "ddi-fw",
        "interaction",
        ["fluconazole", "warfarin"],
        "interaction",
        "DDInter 2.0: fluconazole + warfarin (Major)",
        "DDInter 2.0 lists an interaction with severity Major between fluconazole and warfarin.",
        source_name="DDInter 2.0",
    ),
]


def chroma_store(path: Path) -> ChromaStore:
    return ChromaStore(make_client(path=path), DIM)


async def build_index(path: Path, rows: list[dict[str, Any]] | None = None) -> ChromaStore:
    store = chroma_store(path)
    await index_chunks(store, FakeEmbedder(DIM), [dict(r) for r in (rows or CORPUS)])
    return store
