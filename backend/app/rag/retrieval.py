"""Hybrid retrieval: BM25 (lexical) + embeddings (dense), fused by reciprocal rank fusion.

- BM25 (Okapi, k1 = 1.2, b = 0.75) over title + text, in memory: the corpus is ~10^4
  chunks, so scoring every chunk takes a few milliseconds. Tokens are lower-cased, accents
  removed, English and French stop words dropped, plural "s" stripped.
- Dense: cosine similarity of bge-m3 vectors, searched in ChromaDB (HNSW, D76) with the
  metadata filters as a `where` clause. Each hit keeps its similarity, which the agent uses
  to judge whether the evidence is good enough (docs/AGENT.md).
- Hybrid: RRF, score = sum over the two lists of 1 / (60 + rank) (Cormack et al., 2009).
Metadata filters (ingredient, document type, section, retracted) apply to all three.
"""

from __future__ import annotations

import asyncio
import math
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Literal

import numpy as np

from app.rag.embeddings import Embedder, fold
from app.rag.store import ChromaStore, Chunk, Filters

QUERY_CACHE = 512  # query embeddings kept in memory (a repeated query skips the embedding)

Mode = Literal["bm25", "dense", "hybrid"]
RRF_K = 60
CANDIDATES = 50

STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "might",
        "more",
        "most",
        "no",
        "not",
        "of",
        "on",
        "or",
        "should",
        "so",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "any",
        "between",
        "both",
        "each",
        "other",
        "also",
        "only",
        "same",
        "use",
        "used",
        "au",
        "aux",
        "avec",
        "ce",
        "ces",
        "dans",
        "de",
        "des",
        "du",
        "elle",
        "en",
        "est",
        "et",
        "eux",
        "il",
        "ils",
        "je",
        "la",
        "le",
        "les",
        "leur",
        "lui",
        "ma",
        "mais",
        "me",
        "meme",
        "mes",
        "moi",
        "mon",
        "ne",
        "nos",
        "notre",
        "nous",
        "ou",
        "par",
        "pas",
        "pour",
        "qu",
        "que",
        "qui",
        "sa",
        "se",
        "ses",
        "son",
        "sur",
        "ta",
        "te",
        "tes",
        "toi",
        "ton",
        "tu",
        "un",
        "une",
        "vos",
        "votre",
        "vous",
        "c",
        "d",
        "j",
        "l",
        "m",
        "n",
        "s",
        "t",
        "y",
        "est",
        "sont",
        "peut",
        "quel",
        "quelle",
        "quels",
        "quelles",
        "quoi",
        "comment",
        "entre",
        "avec",
        "sans",
        "plus",
        "tres",
        "faut",
        "dois",
        "puis",
    ]
)
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    tokens = []
    for token in _TOKEN.findall(fold(text)):
        if token in STOP_WORDS or len(token) < 2:
            continue
        if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(documents)
        lengths = np.zeros(self.n, dtype=np.float32)
        postings: dict[str, tuple[list[int], list[int]]] = {}
        for index, document in enumerate(documents):
            counts = Counter(tokenize(document))
            lengths[index] = sum(counts.values())
            for term, tf in counts.items():
                docs, tfs = postings.setdefault(term, ([], []))
                docs.append(index)
                tfs.append(tf)
        self.lengths = lengths
        self.avg_length = float(lengths.mean()) if self.n else 0.0
        self.postings = {
            term: (np.array(docs, dtype=np.int32), np.array(tfs, dtype=np.float32))
            for term, (docs, tfs) in postings.items()
        }

    def idf(self, term: str) -> float:
        df = len(self.postings[term][0])
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> np.ndarray:
        scores = np.zeros(self.n, dtype=np.float32)
        if not self.n:
            return scores
        norm = self.k1 * (1 - self.b + self.b * self.lengths / max(self.avg_length, 1e-9))
        for term in set(tokenize(query)):
            if term not in self.postings:
                continue
            docs, tfs = self.postings[term]
            scores[docs] += self.idf(term) * tfs * (self.k1 + 1) / (tfs + norm[docs])
        return scores


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    bm25_rank: int | None = None
    dense_rank: int | None = None
    similarity: float | None = None  # cosine similarity to the query (dense and hybrid)


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda item: (-item[1], item[0]))


class Retriever:
    def __init__(self, store: ChromaStore, embedder: Embedder) -> None:
        self.store, self.embedder = store, embedder
        self.chunks = store.load_chunks()
        self.by_id = {chunk.chunk_id: chunk for chunk in self.chunks}
        self.bm25 = BM25([chunk.search_text for chunk in self.chunks])
        # Ingredients the corpus has documents about (the agent's evidence check).
        self.ingredients = {name for chunk in self.chunks for name in chunk.ingredients}
        # First chunk of each (ingredient, label section): get_drug_info reads it directly.
        self.label_sections: dict[tuple[str, str], Chunk] = {}
        for chunk in sorted(self.chunks, key=lambda c: c.chunk_index):
            if chunk.doc_type == "label":
                for name in chunk.ingredients:
                    self.label_sections.setdefault((name, chunk.section), chunk)
        self._vectors: OrderedDict[str, list[float]] = OrderedDict()

    def _mask(self, filters: Filters) -> np.ndarray:
        return np.array([filters.accepts(chunk) for chunk in self.chunks], dtype=bool)

    async def query_vector(self, query: str) -> list[float]:
        """The query's embedding, from memory when the same query was embedded before."""
        if query in self._vectors:
            self._vectors.move_to_end(query)
            return self._vectors[query]
        (vector,) = await self.embedder.embed([query])
        self._vectors[query] = vector
        if len(self._vectors) > QUERY_CACHE:
            self._vectors.popitem(last=False)
        return vector

    def bm25_ranking(self, query: str, filters: Filters, n: int) -> list[str]:
        scores = self.bm25.scores(query)
        mask = self._mask(filters) & (scores > 0)
        order = np.argsort(-scores, kind="stable")
        return [self.chunks[i].chunk_id for i in order if mask[i]][:n]

    async def dense_ranking(self, query: str, filters: Filters, n: int) -> list[tuple[str, float]]:
        """(chunk_id, cosine similarity), best first, searched in Chroma."""
        vector = await self.query_vector(query)
        # The filters are applied here, on the metadata already in memory, and Chroma
        # searches only the allowed ids (much faster than its own metadata filter).
        allowed = [chunk.chunk_id for chunk in self.chunks if filters.accepts(chunk)]
        found = await asyncio.to_thread(self.store.dense_search, vector, filters, n, allowed)
        return [(cid, sim) for cid, sim in found if cid in self.by_id]

    async def search(
        self,
        query: str,
        *,
        k: int = 5,
        mode: Mode = "hybrid",
        filters: Filters | None = None,
        candidates: int = CANDIDATES,
    ) -> list[Hit]:
        filters = filters or Filters()
        lexical = self.bm25_ranking(query, filters, candidates) if mode != "dense" else []
        scored = await self.dense_ranking(query, filters, candidates) if mode != "bm25" else []
        dense = [cid for cid, _ in scored]
        similarity = dict(scored)
        lexical_rank = {cid: r for r, cid in enumerate(lexical, start=1)}
        dense_rank = {cid: r for r, cid in enumerate(dense, start=1)}
        if mode == "bm25":
            fused = [(cid, 1.0 / (RRF_K + r)) for cid, r in lexical_rank.items()]
        elif mode == "dense":
            fused = [(cid, 1.0 / (RRF_K + r)) for cid, r in dense_rank.items()]
        else:
            fused = rrf([lexical, dense])
        return [
            Hit(
                self.by_id[cid],
                score,
                lexical_rank.get(cid),
                dense_rank.get(cid),
                similarity.get(cid),
            )
            for cid, score in fused[:k]
        ]


class RetrieverHolder:
    """Builds the retriever on first use and again whenever the index is rebuilt."""

    def __init__(self, store: ChromaStore, embedder: Embedder) -> None:
        self.store, self.embedder = store, embedder
        self._retriever: Retriever | None = None
        self._version: str | None = None
        self._lock = threading.Lock()

    @property
    def version(self) -> str | None:
        """`indexed_at` of the loaded index: cached answers are only valid for one version."""
        return self._version

    def get(self) -> Retriever | None:
        """None when the index does not exist yet (`python -m app.rag.index`)."""
        with self._lock:
            if not self.store.exists():
                return None
            version = self.store.get_meta().get("indexed_at")
            if self._retriever is None or version != self._version:
                self._retriever = Retriever(self.store, self.embedder)
                self._version = version
            return self._retriever
