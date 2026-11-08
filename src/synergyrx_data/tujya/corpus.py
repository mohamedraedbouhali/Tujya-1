"""Tujya RAG corpus: openFDA label sections, PubMed abstracts and DDInter rows -> chunks.

Standard chunking (D85): every text is cut into chunks of at most `CHUNK_SIZE` characters,
at the largest boundary that fits (paragraph, line, sentence, clause, word), each chunk
starting with the last ~`CHUNK_OVERLAP` characters of the one before, as LangChain's
RecursiveCharacterTextSplitter does.

- labels: each section is chunked on its own (the section stays in the metadata, for the
  section filters), after the manufacturer / "Revised:" boilerplate at its end is removed;
- abstracts: the whole abstract is chunked as one text, so a short "OBJECTIVE:" paragraph
  keeps the results that follow it;
- DDInter: one chunk per interacting pair between the class ingredients (already short).

Every chunk carries its metadata (`CHUNK_COLUMNS`, documented in docs/RAG.md). Dosage
sections are refused here a second time, whatever the connector stored.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

CHUNK_SIZE = 1000  # characters, about 250 tokens
CHUNK_OVERLAP = 200
SEPARATORS = ("\n\n", "\n", ". ", "; ", ", ", " ")
FORBIDDEN_SECTION = re.compile(r"dosage|dose|overdos|how_supplied|package_label")

CHUNK_COLUMNS = [
    "chunk_id",
    "doc_id",
    "doc_type",  # label | abstract | interaction
    "ingredients",  # the ingredient(s) the document is about, lower-case RxNorm names
    "mentioned_ingredients",  # other class ingredients named in the chunk text
    "section",  # label section, abstract paragraph label, or "interaction"
    "chunk_index",
    "title",
    "text",
    "source_name",
    "url",
    "date",  # label effective_time, publication year, DDInter release
    "version",  # label version, PubMed record, DDInter version
    "license",
    "article_type",  # PubMed only
    "is_retracted",  # PubMed only (False elsewhere)
    "language",
    "retrieved_at",
]
SECTION_TITLES = {
    "boxed_warning": "Boxed warning",
    "indications_and_usage": "Indications and usage",
    "contraindications": "Contraindications",
    "warnings_and_cautions": "Warnings and precautions",
    "warnings": "Warnings",
    "precautions": "Precautions",
    "general_precautions": "General precautions",
    "drug_interactions": "Drug interactions",
    "drug_and_or_laboratory_test_interactions": "Drug and laboratory test interactions",
    "adverse_reactions": "Adverse reactions",
    "use_in_specific_populations": "Use in specific populations",
    "pregnancy": "Pregnancy",
    "lactation": "Lactation",
    "nursing_mothers": "Nursing mothers",
    "pediatric_use": "Pediatric use",
    "geriatric_use": "Geriatric use",
    "information_for_patients": "Information for patients",
    "mechanism_of_action": "Mechanism of action",
}
_PARAGRAPH_LABEL = re.compile(r"^([A-Z][A-Z /&,-]{2,60}):\s+")
# The end of a patient leaflet: who made it, when it was revised, a logo's file name.
_LABEL_TAIL = re.compile(
    r"Brands listed are the trademarks|"
    r"\b(?:Manufactured|Distributed|Marketed|Packaged|Made) (?:by|for)\b\s*:?",
    re.IGNORECASE,
)
_LABEL_NOISE = re.compile(r"\bRevised:\s*\d{1,2}/\d{2,4}\b|\b\S+-logo\b", re.IGNORECASE)
TAIL_CHARS = 600  # only that far from the end: a "distributed by" earlier is real content


def chunk_id(*parts: object) -> str:
    text = "|".join(str(p) for p in parts)
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _pieces(text: str, size: int, separators: tuple[str, ...]) -> list[str]:
    """Cut `text` into pieces of at most `size` characters at the first separator found,
    then the next ones for pieces still too long. Each piece keeps its separator."""
    if len(text) <= size:
        return [text]
    for index, separator in enumerate(separators):
        if separator not in text:
            continue
        parts = text.split(separator)
        found: list[str] = []
        for number, part in enumerate(parts):
            piece = part if number == len(parts) - 1 else part + separator
            if not piece:
                continue
            if len(piece) <= size:
                found.append(piece)
            else:
                found += _pieces(piece, size, separators[index + 1 :])
        return found
    return [text[start : start + size] for start in range(0, len(text), size)]


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Standard recursive chunking: chunks of at most `chunk_size` characters, cut at the
    largest boundary that fits, each starting with the last pieces (at most `overlap`
    characters) of the chunk before."""
    text = text.strip()
    if len(text) <= chunk_size:
        return [text] if text else []
    chunks: list[str] = []
    current: list[str] = []
    for piece in _pieces(text, chunk_size, SEPARATORS):
        if current and sum(map(len, current)) + len(piece) > chunk_size:
            chunks.append("".join(current).strip())
            tail: list[str] = []
            for previous in reversed(current):
                if sum(map(len, tail)) + len(previous) > overlap:
                    break
                tail.insert(0, previous)
            current = tail
            while current and sum(map(len, current)) + len(piece) > chunk_size:
                current.pop(0)
        current.append(piece)
    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def clean_label_text(text: str) -> str:
    """A label section without the leaflet's closing lines (maker, revision date, logo)."""
    tail = _LABEL_TAIL.search(text, max(0, len(text) - TAIL_CHARS))
    if tail:
        text = text[: tail.start()]
    return re.sub(r"[ \t]{2,}", " ", _LABEL_NOISE.sub("", text)).strip()


def mentions(text: str, names: Iterable[str]) -> list[str]:
    lowered = text.lower()
    return sorted(n for n in names if re.search(rf"\b{re.escape(n)}\b", lowered))


def label_chunks(sections: pd.DataFrame, names: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in sections.itertuples(index=False):
        if FORBIDDEN_SECTION.search(row.section):
            raise ValueError(f"dosage section must never be indexed: {row.section}")
        product = row.brand_name or row.generic_name or row.ingredient
        heading = SECTION_TITLES.get(row.section, row.section.replace("_", " ").capitalize())
        title = f"{row.ingredient.capitalize()} label ({product}): {heading}"
        for index, piece in enumerate(split_text(clean_label_text(row.text))):
            rows.append(
                {
                    "chunk_id": chunk_id("label", row.label_id, row.section, index),
                    "doc_id": f"openfda:{row.label_id}",
                    "doc_type": "label",
                    "ingredients": [row.ingredient],
                    "mentioned_ingredients": [
                        n for n in mentions(piece, names) if n != row.ingredient
                    ],
                    "section": row.section,
                    "chunk_index": index,
                    "title": title,
                    "text": piece,
                    "source_name": "openFDA drug label",
                    "url": row.label_url or row.source_url,
                    "date": row.effective_time,
                    "version": f"set_id {row.set_id} v{row.label_version}",
                    "license": row.license,
                    "article_type": None,
                    "is_retracted": False,
                    "language": "en",
                    "retrieved_at": row.retrieved_at,
                }
            )
    return rows


def paragraphs(abstract: str) -> list[tuple[str, str]]:
    """(label, text) per abstract paragraph; unlabelled paragraphs get "abstract"."""
    found = []
    for line in abstract.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = _PARAGRAPH_LABEL.match(line)
        if match:
            found.append((match.group(1).strip().lower(), line[match.end() :].strip()))
        else:
            found.append(("abstract", line))
    return found


def abstract_chunks(
    articles: pd.DataFrame, ingredients_by_pmid: dict[str, list[str]], names: set[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in articles.itertuples(index=False):
        if not isinstance(row.abstract, str) or not row.abstract.strip():
            continue
        about = ingredients_by_pmid.get(row.pmid, [])
        # The whole abstract, one paragraph per line ("RESULTS: ..."), chunked as one text.
        text = "\n".join(
            line if label == "abstract" else f"{label.upper()}: {line}"
            for label, line in paragraphs(row.abstract)
        )
        for index, piece in enumerate(split_text(text)):
            rows.append(
                {
                    "chunk_id": chunk_id("pubmed", row.pmid, index),
                    "doc_id": f"pubmed:{row.pmid}",
                    "doc_type": "abstract",
                    "ingredients": about,
                    "mentioned_ingredients": [n for n in mentions(piece, names) if n not in about],
                    "section": "abstract",
                    "chunk_index": index,
                    "title": str(row.title or f"PubMed {row.pmid}"),
                    "text": piece,
                    "source_name": f"PubMed ({row.journal})" if row.journal else "PubMed",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{row.pmid}/",
                    "date": "" if pd.isna(row.year) else str(int(row.year)),
                    "version": f"PMID {row.pmid}",
                    "license": row.license,
                    "article_type": row.article_type,
                    "is_retracted": bool(row.is_retracted),
                    "language": (row.language or "eng")[:2],
                    "retrieved_at": row.retrieved_at,
                }
            )
    return rows


def interaction_chunks(pairs: pd.DataFrame, retrieved_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in pairs.itertuples(index=False):
        a, b = row.ingredient_a, row.ingredient_b
        if row.severity == "Unknown":
            level = "an interaction whose severity DDInter does not grade (level Unknown)"
        else:
            level = f"an interaction with severity {row.severity}"
        text = (
            f"DDInter 2.0 lists {level} between {a} and {b}. "
            "DDInter's bulk files give only the two drugs and the level, not the mechanism."
        )
        rows.append(
            {
                "chunk_id": chunk_id("ddinter", a, b),
                "doc_id": f"ddinter:{row.ddinter_id_a}:{row.ddinter_id_b}",
                "doc_type": "interaction",
                "ingredients": [a, b],
                "mentioned_ingredients": [],
                "section": "interaction",
                "chunk_index": 0,
                "title": f"DDInter 2.0: {a} + {b} ({row.severity})",
                "text": text,
                "source_name": "DDInter 2.0",
                "url": row.source_url,
                "date": "2025",
                "version": "DDInter 2.0",
                "license": row.license,
                "article_type": None,
                "is_retracted": False,
                "language": "en",
                "retrieved_at": retrieved_at,
            }
        )
    return rows


def pmid_ingredients(raw_pubmed: Path, query_hits: pd.DataFrame) -> dict[str, list[str]]:
    """PMID -> ingredients whose query returned it (from each query's `query.json`)."""
    names: dict[str, str] = {}
    for path in raw_pubmed.glob("*/*/query.json"):
        query = json.loads(path.read_text(encoding="utf-8"))
        if query.get("kind") == "ingredient":
            names[query["query_id"]] = query["drug_names"][0]
    found: dict[str, set[str]] = {}
    for row in query_hits.itertuples(index=False):
        if row.query_id in names:
            found.setdefault(row.pmid, set()).add(names[row.query_id])
    return {pmid: sorted(values) for pmid, values in found.items()}


def build_chunks(
    label_sections: pd.DataFrame | None,
    articles: pd.DataFrame | None,
    ingredients_by_pmid: dict[str, list[str]],
    pairs: pd.DataFrame | None,
    names: set[str],
    ddinter_retrieved_at: str = "",
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if label_sections is not None:
        rows += label_chunks(label_sections, names)
    if articles is not None:
        kept = articles[articles["pmid"].isin(list(ingredients_by_pmid))]
        rows += abstract_chunks(kept, ingredients_by_pmid, names)
    if pairs is not None:
        rows += interaction_chunks(pairs, ddinter_retrieved_at)
    frame = pd.DataFrame(rows, columns=CHUNK_COLUMNS)
    if frame["chunk_id"].duplicated().any():
        raise ValueError("duplicate chunk ids")
    return frame


def summary(chunks: pd.DataFrame) -> dict[str, Any]:
    return {
        "chunks": len(chunks),
        "documents": int(chunks["doc_id"].nunique()),
        "by_type": {
            str(k): {"documents": int(g["doc_id"].nunique()), "chunks": len(g)}
            for k, g in chunks.groupby("doc_type")
        },
        "ingredients_covered": len({i for v in chunks["ingredients"] for i in v}),
        "retracted_chunks": int(chunks["is_retracted"].sum()),
        "mean_chars": round(float(chunks["text"].str.len().mean()), 1) if len(chunks) else 0,
    }
