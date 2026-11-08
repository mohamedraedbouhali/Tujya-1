"""RAG retrieval on a real ChromaDB collection with fake embeddings: index, BM25, dense,
hybrid, filters, reloading."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI

from app.rag.embeddings import FakeEmbedder
from app.rag.index import index_chunks
from app.rag.retrieval import BM25, Retriever, RetrieverHolder, rrf, tokenize
from app.rag.store import ChromaStore, Filters, ingredient_key, to_chunk, to_metadata
from app.rag.tools import Toolbox
from tests.rag_fakes import CORPUS, DIM, build_index, chroma_store


@pytest.fixture
def store(tmp_path: Path) -> ChromaStore:
    return asyncio.run(build_index(tmp_path / "chroma"))


def test_index_is_idempotent_and_follows_the_corpus(store: ChromaStore) -> None:
    embedder = FakeEmbedder(DIM)
    rows = [dict(r) for r in CORPUS]
    again = asyncio.run(index_chunks(store, embedder, rows))
    assert again["embedded"] == 0 and again["unchanged"] == len(CORPUS) and embedder.calls == 0
    first_version = store.get_meta()["indexed_at"]

    rows[0] = {**rows[0], "text": rows[0]["text"] + " Updated."}
    changed = asyncio.run(index_chunks(store, embedder, rows[:-1]))
    assert (changed["embedded"], changed["deleted"]) == (1, 1)
    assert len(store.hashes()) == len(CORPUS) - 1 == store.count()
    meta = store.get_meta()
    assert meta["model"] == "fake-hash" and meta["dim"] == str(DIM) and meta["chunks"] == "5"
    assert meta["indexed_at"] >= first_version
    updated = next(c for c in store.load_chunks() if c.chunk_id == rows[0]["chunk_id"])
    assert updated.text.endswith("Updated.")


def test_another_embedding_model_rebuilds_the_collection(store: ChromaStore) -> None:
    other = FakeEmbedder(DIM)
    other.model = "fake-other"
    stats = asyncio.run(index_chunks(store, other, [dict(r) for r in CORPUS]))
    assert stats["embedded"] == len(CORPUS) and store.get_meta()["model"] == "fake-other"


def test_metadata_round_trip() -> None:
    row = dict(CORPUS[4])  # PubMed review that mentions fluconazole
    meta = to_metadata(row, "hash")
    assert meta["ing_warfarin"] is True and meta["ing_fluconazole"] is True
    assert all(isinstance(v, str | int | float | bool) for v in meta.values())
    chunk = to_chunk(row["chunk_id"], row["text"], meta)
    assert chunk.ingredients == ["warfarin"] and chunk.mentioned_ingredients == ["fluconazole"]
    assert chunk.article_type == "review" and chunk.is_retracted is False
    no_type = to_chunk("x", "t", to_metadata({**row, "article_type": None}, "h"))
    assert no_type.article_type is None
    assert ingredient_key("Vitamin B12") == "ing_vitamin_b12"


def test_filters_become_a_chroma_where_clause() -> None:
    assert Filters(exclude_retracted=False).where() is None
    assert Filters().where() == {"is_retracted": False}
    where = Filters(ingredients=("warfarin", "folic acid"), doc_types=("label",)).where()
    assert where == {
        "$and": [
            {"is_retracted": False},
            {"doc_type": {"$in": ["label"]}},
            {"$or": [{"ing_warfarin": True}, {"ing_folic_acid": True}]},
        ]
    }


def test_tokenize_and_bm25() -> None:
    assert tokenize("Les interactions du Fluconazole avec la warfarine") == [
        "interaction",
        "fluconazole",
        "warfarine",
    ]
    bm25 = BM25(["warfarin bleeding", "fluconazole warfarin", "losartan dizziness"])
    scores = bm25.scores("warfarin fluconazole")
    assert scores.argmax() == 1 and scores[2] == 0
    assert rrf([["a", "b"], ["b", "c"]])[0][0] == "b"


def test_three_modes_and_filters(store: ChromaStore) -> None:
    retriever = Retriever(store, FakeEmbedder(DIM))
    query = "fluconazole warfarin prothrombin"
    for mode in ("bm25", "dense", "hybrid"):
        hits = asyncio.run(retriever.search(query, k=3, mode=mode))  # type: ignore[arg-type]
        assert hits and hits[0].chunk.chunk_id in {"flu-di", "ddi-fw"}, mode
        assert all(not h.chunk.is_retracted for h in hits)
        if mode == "bm25":
            assert all(h.similarity is None for h in hits)
        else:
            assert all(h.similarity is not None and -1 <= h.similarity <= 1 for h in hits)
    hybrid = asyncio.run(retriever.search(query, k=6))
    assert any(h.bm25_rank and h.dense_rank for h in hybrid)

    only_labels = Filters(doc_types=("label",), ingredients=("warfarin",))
    hits = asyncio.run(retriever.search("warfarin", k=10, filters=only_labels))
    # "about or mentioning warfarin": the fluconazole label mentions it
    assert {h.chunk.chunk_id for h in hits} == {"war-ci", "flu-di"}
    with_retracted = Filters(ingredients=("warfarin",), exclude_retracted=False)
    ids = {
        h.chunk.chunk_id
        for h in asyncio.run(retriever.search("warfarin", k=10, filters=with_retracted))
    }
    assert "pm-retracted" in ids
    sections = Filters(sections=("contraindications",))
    assert [
        h.chunk.chunk_id for h in asyncio.run(retriever.search("pregnancy", filters=sections))
    ] == ["war-ci"]


def test_chroma_search_matches_brute_force(store: ChromaStore) -> None:
    """HNSW is approximate; at this size and beam width it must equal the exact ranking."""
    embedder = FakeEmbedder(DIM)
    retriever = Retriever(store, embedder)
    chunks = [c for c in retriever.chunks if not c.is_retracted]
    matrix = np.array([embedder.vector(c.search_text) for c in chunks])
    for query in ("warfarin pregnancy", "azole antifungal bleeding", "losartan dizziness"):
        exact = matrix @ np.array(embedder.vector(query))
        expected = [chunks[i].chunk_id for i in np.argsort(-exact)]
        found = asyncio.run(retriever.dense_ranking(query, Filters(), len(chunks)))
        assert [cid for cid, _ in found] == expected
        assert np.allclose([s for _, s in found], np.sort(exact)[::-1], atol=1e-4)


def test_allowed_ids_give_the_same_results_as_the_where_clause(store: ChromaStore) -> None:
    """The Retriever filters in memory and passes ids; Chroma's own filter must agree."""
    embedder = FakeEmbedder(DIM)
    chunks = store.load_chunks()
    vector = embedder.vector("warfarin bleeding fluconazole")
    for filters in (
        Filters(),
        Filters(ingredients=("warfarin",)),
        Filters(ingredients=("fluconazole",), doc_types=("label",)),
        Filters(sections=("contraindications",), exclude_retracted=False),
        Filters(ingredients=("not-in-corpus",)),
    ):
        allowed = [c.chunk_id for c in chunks if filters.accepts(c)]
        assert store.dense_search(vector, filters, 10, allowed) == store.dense_search(
            vector, filters, 10
        ), filters


def test_query_embeddings_are_cached(store: ChromaStore) -> None:
    embedder = FakeEmbedder(DIM)
    retriever = Retriever(store, embedder)
    asyncio.run(retriever.search("warfarin", mode="dense"))
    asyncio.run(retriever.search("warfarin", mode="hybrid"))
    assert embedder.calls == 1


def test_label_sections_and_corpus_ingredients(store: ChromaStore) -> None:
    retriever = Retriever(store, FakeEmbedder(DIM))
    assert retriever.label_sections[("warfarin", "contraindications")].chunk_id == "war-ci"
    assert ("warfarin", "results") not in retriever.label_sections  # abstracts are not labels
    assert retriever.ingredients == {"fluconazole", "warfarin", "losartan"}


def test_holder_reloads_after_reindexing(tmp_path: Path) -> None:
    empty = chroma_store(tmp_path / "chroma")
    holder = RetrieverHolder(empty, FakeEmbedder(DIM))
    assert holder.get() is None and holder.version is None  # no index yet
    asyncio.run(index_chunks(empty, FakeEmbedder(DIM), [dict(r) for r in CORPUS[:2]]))
    first = holder.get()
    assert first is not None and len(first.chunks) == 2 and holder.version is not None
    assert holder.get() is first
    time.sleep(1.1)  # indexed_at has a one-second resolution
    asyncio.run(index_chunks(empty, FakeEmbedder(DIM), [dict(r) for r in CORPUS]))
    second = holder.get()
    assert second is not first and second is not None and len(second.chunks) == len(CORPUS)


def test_a_drug_outside_the_corpus_is_left_to_the_query(
    app: FastAPI, pharma: str, store: ChromaStore
) -> None:
    """Chunks are tagged with the class ingredients only: filtering on another drug name used
    to remove every chunk, even one that discusses it (D85)."""
    toolbox = Toolbox(
        app.state.settings, app.state.pharma_engine, RetrieverHolder(store, FakeEmbedder(DIM))
    )
    both = asyncio.run(
        toolbox.search_documents("warfarin and prednisone", ingredients=["prednisone", "warfarin"])
    )
    assert both["filters"]["ingredients"] == ["warfarin"]
    assert both["filters"]["ignored_ingredients"] == ["prednisone"]
    assert both["results"] and all(
        "warfarin" in r["ingredients"] + r["mentioned_ingredients"] for r in both["results"]
    )
    alone = asyncio.run(toolbox.search_documents("prednisone", ingredients=["prednisone"]))
    assert alone["filters"]["ingredients"] == [] and alone["results"]
