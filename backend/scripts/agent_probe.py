"""Run the real agent on a few probe questions and show how it worked (docs/BENCHMARK.md).

For each question: who planned, the retrieval rounds, every tool call (with its round and
who chose it), the evidence check, the time, and the start of the checked answer. The last
question is asked twice, to show the answer cache.

    cd backend
    python scripts/agent_probe.py            # Ollama running, index built (python -m app.rag.index)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.db import make_engine
from app.rag.runtime import AgentHolder

QUESTIONS = [
    "Quels médicaments de la liste peuvent donner des vertiges ?",
    "Que disent les études sur la warfarine et les saignements ?",
    "What does the losartan label say about breastfeeding?",
    "Quelle est la capitale de la France ?",
    "La warfarine interagit-elle avec le fluconazole ?",
    "La warfarine interagit-elle avec le fluconazole ?",
]


async def main() -> None:
    settings = Settings()
    holder = AgentHolder(settings, make_engine(settings.pharma_database_url))
    print("warm-up:", json.dumps(await holder.warm_up()))
    agent = holder.agent()
    for question in QUESTIONS:
        started = time.perf_counter()
        state = await agent.run(question)
        seconds = time.perf_counter() - started
        report = state.get("agent", {})
        print(f"\n## {question}")
        print(
            f"   {seconds:.2f} s | planner {report.get('planner')} | rounds {report.get('rounds')}"
            f" | cache {report.get('cache')} | safety {state.get('safety', {}).get('action')}"
        )
        for call in state.get("tool_calls", []):
            args = json.dumps(call["args"], ensure_ascii=False)
            chosen = f"round {call.get('round', 1)} {call['chosen_by']:4s}"
            print(f"   {chosen} {call['name']} {args[:110]}")
        evidence = report.get("evidence", {})
        if evidence:
            print(
                f"   evidence: enough={evidence.get('enough')} "
                f"best_similarity={evidence.get('best_similarity')} "
                f"missing={evidence.get('missing')}"
            )
        answer = " ".join(state.get("answer", "").split())
        print(f"   answer: {answer[:260]}")


if __name__ == "__main__":
    asyncio.run(main())
