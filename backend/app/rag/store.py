"""The RAG chunk index in ChromaDB: text, metadata and embedding of every corpus chunk.

One collection (`tujya_chunks`), cosine HNSW. Tujya computes the embeddings itself (bge-m3
through Ollama) and hands them to Chroma: the collection has no embedding function, so
Chroma never downloads or runs a model of its own. Telemetry is off.

Where the index lives (Settings, D76):
- `SYNERGYRX_CHROMA_URL`, e.g. http://chroma:8000: the `chroma` service of docker compose
  (HTTP client), shared by `rag-init` (which writes it) and the backend (which reads it);
- otherwise `SYNERGYRX_CHROMA_PATH`, a local folder (persistent client): local runs, tests.

Chroma metadata values must be scalars (str, int, float, bool), so:
- the ingredient lists are stored as JSON text (`ingredients_json`, `mentioned_json`);
- every ingredient a chunk is about OR mentions also gets a boolean key `ing_<name>`, which
  is what the ingredient filter matches: {"$or": [{"ing_warfarin": true}, ...]};
- `article_type` is left out when the chunk has none.
The index information (embedding model, dimension, chunk count, `indexed_at`) is the
collection's own metadata.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from app.rag.embeddings import fold

COLLECTION = "tujya_chunks"
# At ~10^4 chunks a wide search beam keeps the approximate HNSW search practically exact
# (checked against brute force in tests/test_rag.py) for about a millisecond per query.
HNSW = {"space": "cosine", "ef_construction": 200, "ef_search": 200, "max_neighbors": 32}
INDEX_KEYS = ("model", "dim", "chunks", "indexed_at")
PAGE = 2000  # rows per get() call when reading the whole collection
METADATA_COLUMNS = (
    "chunk_id",
    "doc_id",
    "doc_type",
    "ingredients",
    "mentioned_ingredients",
    "section",
    "chunk_index",
    "title",
    "text",
    "source_name",
    "url",
    "date",
    "version",
    "license",
    "article_type",
    "is_retracted",
    "language",
)
_SCALARS = ("doc_id", "doc_type", "section", "title", "source_name", "url", "date", "version",
            "license", "language")  # fmt: skip


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    doc_type: str  # label | abstract | interaction
    ingredients: list[str]
    mentioned_ingredients: list[str]
    section: str
    chunk_index: int
    title: str
    text: str
    source_name: str
    url: str
    date: str
    version: str
    license: str
    article_type: str | None
    is_retracted: bool
    language: str

    @property
    def search_text(self) -> str:
        """What is embedded and matched by BM25: the title gives each chunk its context."""
        return f"{self.title}\n{self.text}"


@dataclass(frozen=True)
class Filters:
    """Metadata filters. `ingredients` matches a chunk about OR mentioning one of them."""

    ingredients: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()
    exclude_retracted: bool = True

    def accepts(self, chunk: Chunk) -> bool:
        if self.exclude_retracted and chunk.is_retracted:
            return False
        if self.doc_types and chunk.doc_type not in self.doc_types:
            return False
        if self.sections and chunk.section not in self.sections:
            return False
        if self.ingredients:
            names = set(chunk.ingredients) | set(chunk.mentioned_ingredients)
            if not names & set(self.ingredients):
                return False
        return True

    def where(self) -> dict[str, Any] | None:
        """The same filters as a Chroma `where` clause (None: no filter)."""
        clauses: list[dict[str, Any]] = []
        if self.exclude_retracted:
            clauses.append({"is_retracted": False})
        if self.doc_types:
            clauses.append({"doc_type": {"$in": list(self.doc_types)}})
        if self.sections:
            clauses.append({"section": {"$in": list(self.sections)}})
        if self.ingredients:
            names = [{ingredient_key(n): True} for n in dict.fromkeys(self.ingredients)]
            clauses.append(names[0] if len(names) == 1 else {"$or": names})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def ingredient_key(name: str) -> str:
    """Metadata key of an ingredient: "vitamin B12" -> "ing_vitamin_b12"."""
    return "ing_" + re.sub(r"[^a-z0-9]+", "_", fold(name)).strip("_")


def to_metadata(row: dict[str, Any], content_hash: str) -> dict[str, Any]:
    about = list(row.get("ingredients") or [])
    mentioned = list(row.get("mentioned_ingredients") or [])
    meta: dict[str, Any] = {key: str(row.get(key) or "") for key in _SCALARS}
    meta.update(
        chunk_index=int(row.get("chunk_index") or 0),
        is_retracted=bool(row.get("is_retracted")),
        ingredients_json=json.dumps(about),
        mentioned_json=json.dumps(mentioned),
        content_hash=content_hash,
    )
    if row.get("article_type"):
        meta["article_type"] = str(row["article_type"])
    for name in {*about, *mentioned}:
        meta[ingredient_key(name)] = True
    return meta


def to_chunk(chunk_id: str, text: str, meta: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        ingredients=json.loads(str(meta.get("ingredients_json") or "[]")),
        mentioned_ingredients=json.loads(str(meta.get("mentioned_json") or "[]")),
        chunk_index=int(meta.get("chunk_index") or 0),
        is_retracted=bool(meta.get("is_retracted")),
        article_type=str(meta["article_type"]) if meta.get("article_type") else None,
        **{key: str(meta.get(key) or "") for key in _SCALARS},
    )


def make_client(url: str = "", path: Path | None = None, *, wait_seconds: float = 0) -> ClientAPI:
    """HTTP client of a Chroma server when `url` is set, else a persistent local folder.

    `wait_seconds`: keep trying to reach the server that long (the indexer starts with the
    compose `chroma` service and may be faster than it)."""
    settings = ChromaSettings(anonymized_telemetry=False)
    if url:
        parsed = urlparse(url)
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                return chromadb.HttpClient(
                    host=parsed.hostname or "127.0.0.1",
                    port=parsed.port or (443 if parsed.scheme == "https" else 8000),
                    ssl=parsed.scheme == "https",
                    settings=settings,
                )
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
    if path is None:
        raise ValueError("give a Chroma server URL or a folder for the index")
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=settings)


class ChromaStore:
    """The chunk collection. Every call looks the collection up again, so a backend keeps
    working when `rag-init` rebuilds the collection in another process."""

    def __init__(self, client: ClientAPI, dim: int, name: str = COLLECTION) -> None:
        self.client, self.dim, self.name = client, dim, name

    @classmethod
    def from_settings(cls, settings: Any, dim: int) -> ChromaStore:
        client = make_client(settings.chroma_url, Path(settings.chroma_path))
        return cls(client, dim, settings.chroma_collection)

    def _get(self) -> Collection | None:
        try:
            return self.client.get_collection(self.name)
        except Exception:  # NotFoundError (its class moved between Chroma versions)
            return None

    def _require(self) -> Collection:
        collection = self._get()
        if collection is None:
            raise RuntimeError(f"Chroma collection {self.name} does not exist")
        return collection

    # ------------------------------------------------------------ lifecycle

    def exists(self) -> bool:
        return self._get() is not None

    def create(self) -> None:
        self.client.get_or_create_collection(
            self.name, configuration={"hnsw": HNSW}, embedding_function=None
        )

    def drop(self) -> None:
        if self.exists():
            self.client.delete_collection(self.name)

    def get_meta(self) -> dict[str, str]:
        collection = self._get()
        if collection is None:
            return {}
        return {k: str(v) for k, v in (collection.metadata or {}).items() if k in INDEX_KEYS}

    def set_meta(self, values: dict[str, str]) -> None:
        collection = self._require()
        current = {k: v for k, v in (collection.metadata or {}).items() if k in INDEX_KEYS}
        collection.modify(metadata={**current, **values})

    def count(self) -> int:
        collection = self._get()
        return collection.count() if collection is not None else 0

    # ------------------------------------------------------------- writing

    def _batch(self) -> int:
        try:
            return max(1, min(PAGE, int(self.client.get_max_batch_size())))
        except Exception:
            return PAGE

    def hashes(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for ids, _, metas in self._pages(include=["metadatas"]):
            for chunk_id, meta in zip(ids, metas, strict=True):
                found[chunk_id] = str((meta or {}).get("content_hash", ""))
        return found

    def upsert(self, records: list[dict[str, Any]]) -> None:
        """Records: the chunk columns plus `content_hash` and `embedding`."""
        if not records:
            return
        collection, size = self._require(), self._batch()
        for start in range(0, len(records), size):
            batch = records[start : start + size]
            collection.upsert(
                ids=[r["chunk_id"] for r in batch],
                embeddings=[list(r["embedding"]) for r in batch],
                documents=[r["text"] for r in batch],
                metadatas=[to_metadata(r, r["content_hash"]) for r in batch],
            )

    def delete_ids(self, ids: list[str]) -> None:
        collection, size = self._require(), self._batch()
        for start in range(0, len(ids), size):
            collection.delete(ids=ids[start : start + size])

    # ------------------------------------------------------------- reading

    def _pages(self, include: list[str]) -> Any:
        collection = self._get()
        if collection is None:
            return
        offset = 0
        while True:
            page = collection.get(limit=PAGE, offset=offset, include=include)  # type: ignore[arg-type]
            ids = page["ids"]
            if not ids:
                return
            documents = page.get("documents") or [""] * len(ids)
            metadatas = page.get("metadatas") or [{}] * len(ids)
            yield ids, documents, metadatas
            offset += len(ids)

    def load_chunks(self) -> list[Chunk]:
        chunks = [
            to_chunk(chunk_id, text or "", dict(meta or {}))
            for ids, texts, metas in self._pages(include=["documents", "metadatas"])
            for chunk_id, text, meta in zip(ids, texts, metas, strict=True)
        ]
        return sorted(chunks, key=lambda c: c.chunk_id)

    def dense_search(
        self,
        vector: list[float],
        filters: Filters,
        k: int,
        allowed_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Nearest chunks as (chunk_id, cosine similarity), best first, filters applied.

        `allowed_ids`: the chunks that pass the filters, when the caller already knows them
        (the Retriever keeps every chunk's metadata in memory). Chroma then searches only
        those ids, 8 to 30 times faster than evaluating the same `where` clause on its
        metadata, with the same ranking (measured, docs/RAG.md "ChromaDB run")."""
        collection = self._get()
        if collection is None or k <= 0 or collection.count() == 0:
            return []
        if allowed_ids is not None and not allowed_ids:
            return []
        selection: dict[str, Any] = (
            {"ids": allowed_ids} if allowed_ids is not None else {"where": filters.where()}
        )
        result = collection.query(
            query_embeddings=[vector],
            n_results=k,
            include=["distances"],  # type: ignore[list-item]
            **selection,
        )
        ids = result["ids"][0] if result["ids"] else []
        distances = (result.get("distances") or [[]])[0]
        return [(cid, 1.0 - float(d)) for cid, d in zip(ids, distances, strict=True)]
