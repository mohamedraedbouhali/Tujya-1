"""Text embeddings: bge-m3 served by Ollama in production, a deterministic fake in tests.

bge-m3 is multilingual (100+ languages), so a French question finds English label text.
"""

from __future__ import annotations

import functools
import hashlib
import math
import re
import ssl
import unicodedata
from typing import Protocol

import certifi
import httpx


@functools.cache
def _ssl_context() -> ssl.SSLContext:
    """Built once: loading the certificate bundle costs ~0.2 s, which a new httpx client
    would otherwise pay on every embedding call (measured, D78)."""
    return ssl.create_default_context(cafile=certifi.where())


class Embedder(Protocol):
    model: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingError(RuntimeError):
    """The embedding service is unreachable or answered something unusable."""


class OllamaEmbedder:
    """POST /api/embed on the Ollama server (docker compose service `ollama`)."""

    def __init__(
        self,
        base_url: str,
        model: str = "bge-m3",
        dim: int = 1024,
        *,
        num_ctx: int | None = None,
        keep_alive: str | None = None,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url, self.model, self.dim = base_url.rstrip("/"), model, dim
        self.timeout, self.transport = timeout, transport
        self.options = {"num_ctx": num_ctx} if num_ctx else {}
        # How long Ollama keeps the model in GPU memory after a call: reloading bge-m3
        # costs about a second, so the app keeps it loaded between questions.
        self.keep_alive = keep_alive

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = {
            "model": self.model,
            "input": texts,
            "truncate": True,
            **({"options": self.options} if self.options else {}),
            **({"keep_alive": self.keep_alive} if self.keep_alive else {}),
        }
        for attempt in (1, 2):  # once more if Ollama was busy swapping models on the GPU
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, transport=self.transport, verify=_ssl_context()
                ) as client:
                    response = await client.post(f"{self.base_url}/api/embed", json=body)
                    response.raise_for_status()
                break
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise EmbeddingError(
                        f"Ollama embeddings failed: {type(exc).__name__} {exc}"
                    ) from exc
        vectors: list[list[float]] = response.json().get("embeddings", [])
        if len(vectors) != len(texts) or any(len(v) != self.dim for v in vectors):
            raise EmbeddingError(f"unexpected embedding shape from {self.model}")
        return vectors


_WORD = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    """Lower case without accents: "Warfarine sûre" -> "warfarine sure"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class FakeEmbedder:
    """Hashed bag of words and character trigrams, L2-normalised. Deterministic, offline.

    Texts sharing words get similar vectors, which is enough to test the retrieval code
    without a model (CI never downloads embeddings).
    """

    model = "fake-hash"

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim
        self.calls = 0

    def vector(self, text: str) -> list[float]:
        values = [0.0] * self.dim
        for word in _WORD.findall(fold(text)):
            features = [word] + [word[i : i + 3] for i in range(max(0, len(word) - 2))]
            for feature in features:
                digest = hashlib.md5(feature.encode(), usedforsecurity=False).digest()
                index = int.from_bytes(digest[:4], "little") % self.dim
                values[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self.vector(t) for t in texts]
