# RAG corpus and retrieval

Documents the Tujya agent answers from: what they are, how they were collected, how they
are cut into chunks, what metadata each chunk carries, and how they are searched. Built on
2026-10-28. Decisions: D59 to D62 in docs/DECISIONS.md.

```
config/pill_classes.csv (82 active ingredients of the 150 pill classes)
  -> openFDA drug labels      python -m synergyrx_data.tujya labels   -> data/rag/raw, interim
  -> PubMed abstracts         python -m synergyrx_data.tujya pubmed   -> data/rag/raw, interim
  -> DDInter pairs            data/tujya/interactions_between_classes.csv (docs/INTERACTIONS.md)
  -> chunks + metadata        dvc repro rag_corpus  (= python -m synergyrx_data.tujya corpus)
                              -> data/rag/corpus/chunks.parquet, summary.json
  -> embeddings + index       python -m app.rag.index  (backend)  -> ChromaDB collection tujya_chunks
```

Commands run from the repository root with the pipeline venv (`.venv-dev`); without a
`.env` add `--set http.require_contact_email=false` (as in docs/INTERACTIONS.md). The two
fetch steps reuse the pipeline's connectors (PoliteClient: rate limits, retries, HTTP cache,
manifest with SHA-256 and provenance), in their own data folder `data/rag/` with its own
manifest `data/rag/manifest.json`, so they never mix with the SynergyRx files under
`data/raw`.

## Sources and counts

| Document type | Source | Licence | Documents | Chunks |
|---|---|---|---:|---:|
| `label` | openFDA drug labels (SPL), https://open.fda.gov/apis/drug/label/ | CC0 / US public domain (openFDA terms) | 82 (one per ingredient) | 4,142 |
| `abstract` | PubMed via NCBI E-utilities | NLM terms; abstracts may be under publisher copyright (research use, not redistributed) | 1,490 | 3,203 |
| `interaction` | DDInter 2.0 (pairs between the 82 ingredients) | CC BY-NC-SA 4.0 | 2,350 | 2,350 |
| **Total** | | | **3,922** | **9,695** |

Counts of the corpus rebuilt with standard chunking (D85, 2026-11-01). All 82 ingredients have
a label and abstracts. Mean chunk length 625 characters (labels 804, abstracts 713).

### openFDA labels (`openfda_label` connector)

`src/synergyrx_data/connectors/openfda.py`, registered with the other connectors (off by
default, so the SynergyRx `update` run does not fetch it). For each ingredient it asks
`api.fda.gov/drug/label.json` for the 25 most recent labels (`sort=effective_time:desc`)
whose `openfda.generic_name` or `openfda.substance_name` contains the ingredient (or a
search alias: valproate -> valproic acid / divalproex, vitamin B12 -> cyanocobalamin, vitamin
B6 -> pyridoxine), prescription products first, then any product type if none matches.

**Selection rule (D60)**, the first criterion that differs decides:

1. the label is about the ingredient (one of its generic or substance names contains every
   word of the ingredient name: "CYCLOBENZAPRINE HYDROCHLORIDE" is about cyclobenzaprine);
2. single-ingredient product before combination product;
3. prescription (`HUMAN PRESCRIPTION DRUG`) before OTC;
4. the most indexed sections (a repackager label without "drug interactions" loses);
5. the most recent `effective_time`.

Result: 81 prescription labels and 1 OTC (fexofenadine, sold OTC in the US); 80 single-
ingredient; pseudoephedrine and vitamin B6 only exist in combination products
(brompheniramine + pseudoephedrine + dextromethorphan; doxylamine + pyridoxine). Effective
dates 2021-09-30 to 2026-09-11, 80 of 82 since 2024. Each raw file
`data/rag/raw/openfda_label/current/labels/<ingredient>.json` keeps the chosen label and the
list of candidates it was chosen from, so the choice can be audited. Rate: 3 requests/s
(openFDA allows 240/min without a key); answers are cached on disk.

**Sections kept** (in label order): boxed_warning, indications_and_usage, contraindications,
warnings_and_cautions, warnings, precautions, general_precautions, drug_interactions,
drug_and_or_laboratory_test_interactions, adverse_reactions, use_in_specific_populations,
pregnancy, lactation, nursing_mothers, pediatric_use, geriatric_use,
information_for_patients, mechanism_of_action. Old-format labels put interactions under
`precautions`; both formats are covered. 11.9 sections per label on average.

**Never stored (D60):** `dosage_and_administration`, `dosage_forms_and_strengths`,
`overdosage`, `how_supplied`, `package_label_principal_display_panel`, and the numeric
sections `clinical_pharmacology`, `pharmacokinetics`, `clinical_studies`. They are removed
before the raw file is written, the row schema refuses any section named "dosage" or
"overdos", and the chunker refuses them a third time. The agent therefore cannot quote a
dosing section. Limit: other sections still mention amounts (1,122 of 9,695 chunks contain
"<number> mg", e.g. "patients receiving 200 mg" in adverse reactions); the agent's safety
node removes any sentence with a dose from its answers (docs/AGENT.md).

### PubMed abstracts (existing `pubmed` connector, mode `ingredients`)

The PubMed connector gained a third query mode, `ingredients` (D61): one query per
ingredient, `<ingredient block> AND (interactions OR adverse effects) AND hasabstract AND
english[la]`, where the ingredient block is the existing one (`[tiab]`, `[mh]`, `[nm]`) and
the topic block is `"Drug Interactions"[mh] OR interaction*[tiab] OR "adverse effects"[sh]
OR "Drug-Related Side Effects and Adverse Reactions"[mh] OR "adverse effect*"[tiab] OR
"adverse event*"[tiab] OR "adverse reaction*"[tiab] OR contraindicat*[tiab]`, entered since
2000-01-01, sorted by relevance (`sort=relevance`, new option), **at most 20 records per
ingredient**. Every query reached the cap (82 truncated queries): PubMed has many more.
1,617 hits, 1,570 distinct articles (44 found by two ingredients), years 1998 to 2026
(median 2014): 805 research, 266 case reports, 248 reviews, 178 clinical trials, 65
meta-analyses, 8 commentaries; **4 retracted** articles (10 chunks in the current corpus), kept with
`is_retracted = true` and excluded at search time by default.

### DDInter rows

The 2,350 pairs where both ingredients belong to the pill classes (docs/INTERACTIONS.md),
one chunk each: "DDInter 2.0 lists an interaction with severity Major between fluconazole
and warfarin. DDInter's bulk files give only the two drugs and the level, not the
mechanism." "Unknown" is written as "an interaction whose severity DDInter does not grade",
never as "no interaction". The 40,508 pairs with any drug stay out of the text index (they
would drown the other documents in near-identical sentences); the `check_interaction` tool
reads all of them from the database (D62).

## Chunking (`src/synergyrx_data/tujya/corpus.py`)

Standard recursive chunking (D85), as LangChain's `RecursiveCharacterTextSplitter`: chunks of
at most **1,000 characters** (`CHUNK_SIZE`, about 250 tokens), cut at the largest boundary
that fits (paragraph, line, sentence, clause, word), each starting with the last pieces of
the chunk before, up to **200 characters of overlap** (`CHUNK_OVERLAP`). A text with no
boundary at all is cut every 1,000 characters.

- **Labels: each section on its own**, so the `section` metadata and the section filters
  still work. The closing lines of a patient leaflet (manufacturer, "Revised: 07/2026", a
  logo's file name) are removed first, only within the last 600 characters of a section.
- **Abstracts: the whole abstract as one text**, one paragraph per line ("RESULTS: ...");
  `section = "abstract"`. The earlier per-paragraph chunks left 647 one-line fragments such
  as an "OBJECTIVE:" sentence without its results; 78 chunks under 200 characters remain
  (short abstracts and overlapping tails).
- **DDInter: one chunk per pair** (already short).

Measured against the previous chunking (by section / paragraph, at most 1,500 characters),
by document title over the 75 benchmark questions and 30 literature questions written from
random abstracts (dense search with the agent's ingredient filter): first hit right 82.7% on
both for the benchmark (top 5: 94.7% before, 93.3% now; boxed-warning questions gain, a few
drug-pair questions lose a rank), 76.7% -> 93.3% for the literature questions with the
filter fix below, and 31% less text in the top 5 sources sent to the model (3,963 against
5,782 characters).

**Ingredient filter fix (D85).** Chunks are tagged with the 82 class ingredients only. A
question naming another drug (prednisone, misoprostol, terazosin) used to filter every chunk
out, even the abstract that discusses it: 5 of the 30 literature questions found nothing.
`search_documents` now filters on the names the index knows and leaves the others to the
meaning of the query (reported as `ignored_ingredients`).
- Each chunk gets a title that gives its context ("Fluconazole label (Diflucan): Drug
  interactions", the article title, "DDInter 2.0: fluconazole + warfarin (Major)"). The
  title and the text are what BM25 and the embeddings see.
- `chunk_id` is a hash of (document, section, position), so the same input gives the same
  ids and the indexing step can be incremental.

## Metadata schema (one row per chunk, `data/rag/corpus/chunks.parquet`)

| Column | Type | Meaning |
|---|---|---|
| `chunk_id` | string | stable id (16 hex characters) |
| `doc_id` | string | `openfda:<label id>`, `pubmed:<PMID>`, `ddinter:<id a>:<id b>` |
| `doc_type` | string | `label`, `abstract` or `interaction` |
| `ingredients` | list of strings | the ingredient(s) the document is about (lower-case RxNorm names) |
| `mentioned_ingredients` | list of strings | other class ingredients named in the chunk text |
| `section` | string | label section (e.g. `drug_interactions`), abstract paragraph label (`results`), or `interaction` |
| `chunk_index` | int | position of the chunk in its document |
| `title` | string | context title (see above) |
| `text` | string | the chunk text |
| `source_name` | string | "openFDA drug label", "PubMed (<journal>)", "DDInter 2.0" |
| `url` | string | DailyMed page of the label (`drugInfo.cfm?setid=...`), PubMed page, DDInter |
| `date` | string | label `effective_time` (YYYYMMDD), publication year, DDInter release year |
| `version` | string | label `set_id` and version, `PMID <n>`, `DDInter 2.0` |
| `license` | string | licence of the source |
| `article_type` | string or null | PubMed only: research, review, meta_analysis, clinical_trial, case_report, commentary |
| `is_retracted` | bool | PubMed only (retracted publication or "RetractionIn"); false elsewhere |
| `language` | string | `en` |
| `retrieved_at` | string | when the source was downloaded (UTC, ISO 8601) |

## Versioning (DVC)

- `data/rag/raw.dvc`, `data/rag/interim.dvc`, `data/rag/manifest.json.dvc`: the downloaded
  labels and PubMed XML, the parsed tables, and the manifest (URL, SHA-256, size, licence,
  retrieval time of every raw file), tracked with `dvc add` (they come from the network, so
  they are not a pipeline stage).
- `dvc.yaml` stage `rag_corpus`: `python -m synergyrx_data.tujya corpus`, from
  `data/rag/interim`, `data/rag/raw/pubmed`, the two DDInter / ingredient tables and the
  chunker code to `data/rag/corpus` (`dvc.lock` records the hashes). `dvc repro rag_corpus`
  rebuilds the chunks when any input changes.
- Pushed to the default DVC remote with the images (local folder outside the repository,
  D71, docs/INFRA.md); a fresh clone gets the corpus with `dvc pull`.
- Nothing under `data/` is committed to git (some sources forbid redistribution).

## Embeddings and index (backend, `backend/app/rag/`)

- **Embeddings: bge-m3** (1,024 dimensions, multilingual) through Ollama's `/api/embed`
  (D59). Each chunk is embedded as `title + "\n" + text`.
- **Store: ChromaDB** (since 2026-11-01, D76; before: a pgvector table). One collection,
  `tujya_chunks`, cosine HNSW (`ef_search` 200, practically exact at this size). Tujya hands
  Chroma the bge-m3 vectors: the collection has no embedding function, so Chroma never
  downloads or runs a model, and telemetry is off. Document = chunk text, id = `chunk_id`,
  metadata = the scalar columns of the schema above plus `content_hash`. Chroma metadata
  values must be scalars, so the ingredient lists are kept as JSON text
  (`ingredients_json`, `mentioned_json`) **and** as one boolean key per ingredient
  (`ing_warfarin: true` when the chunk is about or mentions warfarin), which is what the
  ingredient filter matches. The collection's own metadata keeps the embedding model, the
  dimension, the chunk count and `indexed_at`.
- **Where it lives:** `SYNERGYRX_CHROMA_URL` (docker compose: the `chroma` service,
  `http://chroma:8000`, volume `chroma`; host port `127.0.0.1:8001`) or, when empty,
  `SYNERGYRX_CHROMA_PATH`, a local folder (default `data/rag/chroma`, git-ignored).
- **Indexing:** `python -m app.rag.index` (backend venv; `--chroma-url` or `--chroma-path`,
  `--chunks`, `--pull` to pull the Ollama models first). Idempotent: a chunk is embedded
  again only if its hash (text, metadata, model) changed, chunks gone from the corpus are
  deleted, a new embedding model rebuilds the collection. Measured runs: section "ChromaDB
  run" below. **With a local Chroma folder (no `chroma_url`), restart the API after
  re-indexing from another process:** its Chroma client keeps the old index in memory, and
  `search_documents` then fails with "Error finding id" for deleted chunks (seen after the
  D85 rebuild). A Chroma server (docker compose) has no such issue.

## Retrieval (`backend/app/rag/retrieval.py`)

| Mode | How | Time per query (8,661 chunks, laptop) |
|---|---|---:|
| `bm25` | Okapi BM25 (k1 1.2, b 0.75) in memory over title + text; lower case, accents removed, English and French stop words, plural "s" stripped | ~6 ms |
| `dense` | bge-m3 query vector, Chroma HNSW cosine search with the filters as a `where` clause; each hit keeps its cosine similarity | see "ChromaDB run" below |
| `hybrid` | both lists (50 candidates each) fused by reciprocal rank fusion, score = sum 1 / (60 + rank) | see below |

Loading the retriever (all chunk texts for BM25, and the first chunk of every label section
for `get_drug_info`) happens once; it reloads by itself when `indexed_at` changes. Query
embeddings are kept in memory (512 queries): a repeated query skips the embedding call.

**Filters** (all modes): `ingredients` (chunks about OR mentioning one of them),
`doc_types` (label, abstract, interaction), `sections`, `exclude_retracted` (default
true). In Chroma: `{"$and": [{"is_retracted": false}, {"doc_type": {"$in": [...]}},
{"$or": [{"ing_warfarin": true}, {"ing_fluconazole": true}]}]}`.

Try it: `python scripts/search.py "warfarin bleeding" --ingredient fluconazole --doc-type
label` (prints the three modes with their ranks and timings).

Which mode is best is measured in docs/BENCHMARK.md: dense with the ingredient filter is the
agent's default since D65 (`SYNERGYRX_RAG_SEARCH_MODE`).

Tests (CI, no model): `backend/tests/test_rag.py`, on a real ChromaDB collection in a
temporary folder with fake hashed embeddings: index idempotence, model change, metadata
round trip, filters as a `where` clause, BM25, the three modes and their similarities,
**Chroma's HNSW ranking equal to an exact brute-force ranking**, the query-embedding cache,
the label-section index, reload after reindexing. CI needs no database service for them.

## ChromaDB run (2026-11-01)

The store moved to ChromaDB (D76) and the corpus was rebuilt on the second PC, the DVC remote
of D71 having been deleted (D80):

| Document type | Documents | Chunks | Versioned corpus of 2026-10-28 |
|---|---:|---:|---|
| `label` (openFDA) | 82 | 2,898 | 82 / 2,895 |
| `abstract` (PubMed) | 1,490 | 3,685 | 1,570 / 3,416 |
| `interaction` (DDInter 2.0) | 2,350 | 2,350 | identical |
| **Total** | **3,922** | **8,933** | 4,002 / 8,661 |

The DDInter part is identical; the openFDA labels and the PubMed abstracts were fetched
again and differ (newer labels, another relevance ranking at PubMed). 21 chunks of retracted
articles, excluded at search time as before.

Measured on 2026-11-01 on the second PC (RTX 4050 Laptop 6 GB, Ollama 0.40.13 installed
on Windows, bge-m3 100 % on the GPU, ChromaDB 1.5.9 as a local folder):

- **Indexing:** 8,933 chunks embedded and stored in **486 s** (18 chunks/s); a second run
  `{"embedded": 0, "unchanged": 8933, "seconds": 0.0}`. The collection takes 103 MB.
- **Benchmark set on this corpus:** `scripts/bench_build.py --allow-missing` rebuilds the
  expected chunks from `benchmark/spec.json`: **80 questions** (75 with expected chunks),
  in `benchmark/rag_questions_rebuilt.jsonl`. 8 of the 9 PubMed-article questions are left
  out, their articles not being in this PubMed sample; the 24 interaction and 50 label
  questions are all there.
- **Retrieval** (`benchmark/results_retrieval_chroma.json`, same metrics as
  docs/BENCHMARK.md):

| Mode | Filter | Recall@1 | Recall@5 | Recall@10 | MRR | Before D85 (R@5 / MRR) | Old corpus, pgvector (R@5 / MRR) |
|---|---|---:|---:|---:|---:|---|---|
| BM25 | none | 0.587 | 0.760 | 0.853 | 0.659 | 0.773 / 0.642 | 0.735 / 0.637 |
| dense (bge-m3) | none | 0.773 | 0.920 | 0.947 | 0.842 | 0.907 / 0.836 | 0.904 / 0.841 |
| hybrid (RRF) | none | 0.773 | 0.933 | 0.973 | 0.849 | 0.907 / 0.821 | 0.892 / 0.779 |
| BM25 | names | 0.600 | 0.773 | 0.867 | 0.674 | 0.813 / 0.669 | 0.783 / 0.660 |
| **dense (bge-m3)** | **names** | **0.800** | **0.920** | **0.947** | **0.856** | 0.933 / 0.849 | 0.928 / 0.852 |
| hybrid (RRF) | names | 0.747 | 0.933 | 0.973 | 0.838 | 0.920 / 0.822 | 0.904 / 0.796 |

  Measured again on 2026-11-01 after the standard chunking (D85, 9,695 chunks; the question
  file rebuilt by `bench_build.py`: same 80 questions and expected documents, 5.35 expected
  chunks per question instead of 4.24). Same conclusion as D65: dense with the ingredient
  filter is the best setting (hybrid now ties it at Recall@5). By language (dense, names):
  Recall@5 0.895 in French, 0.946 in English. The best hit of every answerable question has
  a cosine similarity of at least 0.57 (5th percentile 0.61), so the agent's
  evidence threshold (`rag_min_similarity` 0.45) never sends a good question to a second
  search.

- **Speed of one search, and two fixes found while measuring it** (median over the 80
  questions):

| Step | Before the fixes | After |
|---|---:|---:|
| Query embedding (bge-m3) | 327 ms | 46 ms of Ollama work, no client overhead |
| Chroma search with the ingredient filter | 85-230 ms | 7-20 ms |
| **Whole dense search, new question** | **~400 ms** | **101 ms** (p90 134 ms) |
| Same question again (embedding cached) | | 32 ms |

  1. A new `httpx` client per embedding call rebuilt its TLS context (loading the
     certificate bundle) every time: **233 ms** per call for a 46 ms request. The context is
     now built once (`app/rag/embeddings.py`).
  2. Chroma's metadata `where` filter scans metadata in SQLite: 51 ms for the "not
     retracted" filter, up to 230 ms for an ingredient filter. The Retriever already holds
     every chunk's metadata, so it applies the filters itself and passes Chroma the allowed
     ids (`ids=`): 7-20 ms, **same ranking** (checked on three filters, and by the test
     `test_allowed_ids_give_the_same_results_as_the_where_clause`). The `where` path stays
     for callers without the metadata.

Tests: `backend/tests/test_rag.py` (11 tests on a real Chroma collection, including the
HNSW ranking equal to an exact brute-force ranking) and the whole backend suite pass.

```bash
cd backend
python -m app.rag.index                                   # -> data/rag/chroma
python scripts/bench_build.py --out ../benchmark/rag_questions_rebuilt.jsonl --allow-missing
python scripts/bench_retrieval.py --no-mlflow --questions ../benchmark/rag_questions_rebuilt.jsonl \
    --out ../benchmark/results_retrieval_chroma.json
```

## Tests

`tests/unit/test_tujya_rag.py` (respx, no network): label selection rule, dosage never
stored, connector run (one label per ingredient, 404 handled, raw file reused), PubMed
ingredient queries and their hits, chunk splitting and overlap, chunk metadata, stable ids,
dosage refused by the chunker.
