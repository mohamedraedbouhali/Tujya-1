"""Summary of agent runs (scripts/bench_answers.py output): speed, agentic behaviour, safety.

No judge model is needed: times, planner, retrieval rounds, tool calls, the safety checks
of scripts/bench_generation.py (disclaimer, doses, "safe", uncited timing, refused dose
questions), citations, and whether an expected chunk reached the numbered sources.

    cd backend
    python scripts/bench_agent_summary.py ../data/rag/bench/answers-chroma-auto.jsonl \
        ../data/rag/bench/answers-chroma-llm.jsonl --out ../benchmark/results_agent_chroma.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_generation import claims, safety_scores

from app.rag.safety import CITATION


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [r for r in rows if r["safety"].get("action") != "refused"]
    seconds = [r["seconds"] for r in rows]
    # Time to the first words on screen: every step before the answer, plus the answer's
    # first token (first_token_ms alone counts from the start of the answer step).
    before = ("understand_ms", "plan_ms", "tools_ms", "grade_ms", "refine_ms")
    first = [
        (sum(r["timings"].get(key, 0.0) for key in before) + r["timings"]["first_token_ms"]) / 1000
        for r in rows
        if "first_token_ms" in r["timings"]
    ]
    safety = [safety_scores(r) for r in rows]
    sentences = [s for r in answered for s in claims(r["answer"])]
    cited = [s for s in sentences if CITATION.search(s)]
    with_expected = [r for r in rows if r["expected_chunks"]]
    found = [
        r
        for r in with_expected
        if set(r["expected_chunks"]) & {s.get("chunk_id") for s in r["sources"]}
    ]
    llm_calls = []
    for r in rows:
        agent = r.get("agent", {})
        calls = 1 if r["safety"].get("action") != "refused" or r.get("draft") else 0
        calls += 1 if str(agent.get("planner", "")).startswith("llm") else 0
        calls += max(0, int(agent.get("rounds", 1)) - 1)
        llm_calls.append(calls)
    dose_refusals = [s["dose_question_refused"] for s in safety if "dose_question_refused" in s]
    return {
        "questions": len(rows),
        "seconds_mean": round(statistics.mean(seconds), 2),
        "seconds_median": round(statistics.median(seconds), 2),
        "seconds_p90": round(percentile(seconds, 0.9), 2),
        "seconds_max": round(max(seconds), 2),
        "first_words_median_s": round(statistics.median(first), 2) if first else None,
        "planner": dict(Counter(r.get("agent", {}).get("planner", "?") for r in rows)),
        "rounds": dict(Counter(str(r.get("agent", {}).get("rounds", "?")) for r in rows)),
        "refined_share": round(
            sum(1 for r in rows if r.get("agent", {}).get("refined")) / len(rows), 3
        ),
        "llm_calls_mean": round(statistics.mean(llm_calls), 2),
        "tool_calls_mean": round(statistics.mean(len(r["tool_calls"]) for r in rows), 2),
        "expected_chunk_in_sources": round(len(found) / len(with_expected), 3)
        if with_expected
        else None,
        "answers_with_disclaimer": round(sum(s["has_disclaimer"] for s in safety) / len(rows), 3),
        "dose_sentences": sum(s["dose_sentences"] for s in safety),
        "safe_sentences": sum(s["safe_sentences"] for s in safety),
        "uncited_timing_sentences": sum(s["uncited_timing"] for s in safety),
        "dose_questions_refused": f"{sum(dose_refusals)}/{len(dose_refusals)}",
        "answers_with_a_citation": round(
            sum(1 for r in answered if CITATION.search(r["answer"])) / max(1, len(answered)), 3
        ),
        "sentences_cited": round(len(cited) / max(1, len(sentences)), 3),
        "safety_actions": dict(Counter(r["safety"].get("action") for r in rows)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python scripts/bench_agent_summary.py")
    parser.add_argument("runs", nargs="+", type=Path, help="answers*.jsonl files")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    results = {}
    for path in args.runs:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        settings = {k: rows[0].get(k) for k in ("model", "search_mode", "planner", "max_rounds")}
        results[path.stem] = {"settings": settings, **summarise(rows)}
        print(path.stem, json.dumps(results[path.stem], ensure_ascii=False, indent=1))
    if args.out:
        args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"-> {args.out}")


if __name__ == "__main__":
    main()
