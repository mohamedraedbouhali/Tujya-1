"""Builds the agent's pieces once per app: chunk store, retriever, LLM, toolbox, agent.

Production: Ollama (`SYNERGYRX_OLLAMA_URL`) serves the LLM (`SYNERGYRX_LLM_MODEL`) and the
embeddings (`SYNERGYRX_EMBEDDING_MODEL`); the chunk index is in ChromaDB
(`SYNERGYRX_CHROMA_URL` or `SYNERGYRX_CHROMA_PATH`). With `SYNERGYRX_LLM_PROVIDER=groq` and
`SYNERGYRX_GROQ_API_KEY`, a hosted Groq model writes the answers instead, with the local
model as fallback (D86). Tests replace `llm` and `embedder` with fakes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from sqlalchemy import Engine

from app.config import Settings
from app.rag.agent import TujyaAgent
from app.rag.embeddings import Embedder, OllamaEmbedder
from app.rag.retrieval import RetrieverHolder
from app.rag.store import ChromaStore
from app.rag.tools import Toolbox
from app.scanner import ScannerHolder
from app.toxicity import ToxHolder


def ollama_llm(settings: Settings) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    options: dict[str, Any] = {}
    if settings.llm_model.startswith("qwen3"):
        options["reasoning"] = False  # no hidden "thinking" tokens: faster, same answer
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_url,
        temperature=settings.llm_temperature,
        num_ctx=settings.llm_num_ctx,
        num_predict=settings.llm_max_tokens,
        repeat_penalty=1.1,
        keep_alive=settings.llm_keep_alive,
        client_kwargs={"timeout": settings.llm_timeout_seconds},
        **options,
    )


def groq_llm(settings: Settings) -> BaseChatModel:
    from langchain_groq import ChatGroq

    options: dict[str, Any] = {}
    if settings.groq_model.startswith("qwen/"):
        options["reasoning_effort"] = "none"  # no hidden thinking: faster, same answer
    elif settings.groq_model.startswith("openai/gpt-oss"):
        options["reasoning_effort"] = "low"
    return ChatGroq(  # type: ignore[call-arg]
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.groq_timeout_seconds,
        max_retries=0,  # a rate limit goes straight to the local model, without waiting
        **options,
    )


def make_llm(settings: Settings) -> BaseChatModel | Runnable[Any, Any]:
    """The answering model: Groq with the local Ollama model as fallback, or Ollama alone."""
    local = ollama_llm(settings)
    if settings.llm_provider != "groq":
        return local
    if not settings.groq_api_key.get_secret_value():
        logging.getLogger("tujya").warning("llm_provider=groq without groq_api_key: using Ollama")
        return local
    return groq_llm(settings).with_fallbacks([local])


class AgentHolder:
    def __init__(
        self,
        settings: Settings,
        pharma_engine: Engine,
        scanner: ScannerHolder | None = None,
        *,
        llm: BaseChatModel | Runnable[Any, Any] | None = None,
        embedder: Embedder | None = None,
        toxicity: ToxHolder | None = None,
    ) -> None:
        self.settings, self.pharma_engine, self.scanner = settings, pharma_engine, scanner
        self.toxicity = toxicity
        self.llm = llm
        self.embedder = embedder
        self._toolbox: Toolbox | None = None
        self._agent: TujyaAgent | None = None

    @property
    def model_name(self) -> str:
        """The configured model; each answer reports the one that actually wrote it."""
        if self.settings.llm_provider == "groq" and self.settings.groq_api_key.get_secret_value():
            return self.settings.groq_model
        return str(getattr(self.llm, "model", None) or self.settings.llm_model)

    def toolbox(self) -> Toolbox:
        if self._toolbox is None:
            embedder = self.embedder or OllamaEmbedder(
                self.settings.ollama_url,
                self.settings.embedding_model,
                self.settings.embedding_dim,
                num_ctx=self.settings.embedding_num_ctx,
                keep_alive=self.settings.llm_keep_alive,
            )
            store = ChromaStore.from_settings(self.settings, embedder.dim)
            self._toolbox = Toolbox(
                self.settings,
                self.pharma_engine,
                RetrieverHolder(store, embedder),
                self.scanner,
                toxicity=self.toxicity
                or ToxHolder(self.settings.tox_model_dir, self.settings.ingredient_smiles_file),
            )
        return self._toolbox

    def agent(self) -> TujyaAgent:
        if self._agent is None:
            self.llm = self.llm or make_llm(self.settings)
            self._agent = TujyaAgent(
                self.llm,
                self.toolbox(),
                top_k=self.settings.rag_top_k,
                attribution_threshold=self.settings.rag_attribution_threshold,
                planner=self.settings.agent_planner,
                max_rounds=self.settings.agent_max_rounds,
                topic_similarity=self.settings.rag_topic_similarity,
                min_similarity=self.settings.rag_min_similarity,
                cache_size=self.settings.answer_cache_size,
                cache_seconds=self.settings.answer_cache_seconds,
            )
        return self._agent

    async def warm_up(self) -> dict[str, Any]:
        """Load what the first question would otherwise wait for: the chunk index (BM25 and
        the label sections, ~1 s), the embedding model and the LLM in GPU memory (several
        seconds each on a cold start). Best effort: a failure is reported, never raised."""
        report: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            toolbox = self.toolbox()
        except Exception as exc:  # e.g. the Chroma server is not up yet
            return {"index": f"{type(exc).__name__}: {exc}"[:200]}
        try:
            retriever = await asyncio.to_thread(toolbox.retrievers.get)
            report["chunks"] = len(retriever.chunks) if retriever is not None else 0
        except Exception as exc:
            report["index"] = f"{type(exc).__name__}: {exc}"[:200]
        try:
            await toolbox.retrievers.embedder.embed(["warm-up"])
            report["embeddings"] = "loaded"
        except Exception as exc:
            report["embeddings"] = f"{type(exc).__name__}: {exc}"[:200]
        if self.llm is None:  # the real Ollama model (tests give a fake one)
            try:
                # An empty prompt loads the model and returns at once (Ollama API).
                async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                    response = await client.post(
                        f"{self.settings.ollama_url}/api/generate",
                        json={
                            "model": self.settings.llm_model,
                            "prompt": "",
                            "keep_alive": self.settings.llm_keep_alive,
                        },
                    )
                    response.raise_for_status()
                report["llm"] = "loaded"
            except Exception as exc:
                report["llm"] = f"{type(exc).__name__}: {exc}"[:200]
        report["seconds"] = round(time.perf_counter() - started, 1)
        return report
