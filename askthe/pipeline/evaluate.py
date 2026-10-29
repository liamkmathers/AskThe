"""Run the test set through `ask` in one or more retrieval modes and score the answers.

Each mode runs over every question before the next mode starts, so full mode's large
shared context stays in the prompt cache. Scores are the automated checks in
core/evaluation.py; correctness is left for a person (`correct: null`). When a
reference mode (normally "full") is in the run, other modes are also scored on how
much of what it cited they read.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from askthe.core.evaluation import Price, TestQuestion, cost, recall, score
from askthe.core.interfaces import (
    Embedder,
    KnowledgeStore,
    LLMClient,
    LLMTask,
    SearchIndex,
    VectorIndex,
)
from askthe.core.models import Creator
from askthe.core.profiling import PROFILER_VERSION
from askthe.pipeline.ask import RetrievalSettings, ask

ANSWER_TASKS = (LLMTask.PLAN, LLMTask.RERANK, LLMTask.ANSWER)


def run_eval(
    creator: Creator,
    questions: Sequence[TestQuestion],
    modes: Sequence[str],
    store: KnowledgeStore,
    search: SearchIndex,
    llm: LLMClient,
    vectors: VectorIndex,
    embedder: Embedder,
    settings: RetrievalSettings,
    prices: dict[str, Price],
    label: str,
    reference_mode: str = "full",
    on_progress: Callable[[str, str, dict[str, Any]], None] = lambda qid, mode, result: None,
) -> dict[str, Any]:
    platform_ids = {v.id: v.platform_id for v in store.list_videos(creator.slug)}
    results: dict[str, dict[str, dict[str, Any]]] = {q.id: {} for q in questions}
    for mode in modes:
        mode_settings = replace(settings, mode=mode)
        for q in questions:
            started = time.monotonic()
            r = ask(
                creator,
                q.question,
                store,
                search,
                llm,
                vectors=vectors,
                embedder=embedder,
                settings=mode_settings,
                log=False,
            )
            a = r.answer
            cited = sorted({platform_ids[s.video_id] for s in a.sources})
            read = [platform_ids[v] for v in r.videos_read]
            result = {
                "coverage": a.coverage.value,
                "answer": a.text,
                "sources": [
                    {
                        "n": s.n,
                        "video": platform_ids[s.video_id],
                        "title": s.title,
                        "published": s.published.isoformat(),
                        "segments": s.segment_ids,
                        "quote": s.quote,
                    }
                    for s in sorted(a.sources, key=lambda s: s.n)
                ],
                "problems": a.problems,
                "videos_read": read,
                "segments_read": r.segments_read,
                "context_words": r.trace.get("context_words", 0),
                "queries": r.trace.get("queries", []),
                "warnings": r.trace.get("warnings", []),
                "usage": r.usage_by_model,
                "cost_usd": cost(r.usage_by_model, prices),
                "seconds": round(time.monotonic() - started, 1),
                "checks": score(q, a.text, a.coverage, cited, read, len(a.problems)),
                "correct": None,  # a person's verdict, filled in on review
            }
            results[q.id][mode] = result
            on_progress(q.id, mode, result)

    if reference_mode in modes:
        for by_mode in results.values():
            cited = [i for s in by_mode[reference_mode]["sources"] for i in s["segments"]]
            for mode, result in by_mode.items():
                if mode != reference_mode:
                    result["checks"][f"recall_of_{reference_mode}"] = recall(
                        cited, result["segments_read"]
                    )

    return {
        "label": label,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "creator": creator.slug,
        "modes": list(modes),
        "versions": {
            "profiler": PROFILER_VERSION,
            "models": {t.value: llm.model_for(t) for t in ANSWER_TASKS},
            "embedder": embedder.name,
            "retrieval": {k: v for k, v in vars(settings).items() if k != "mode"},
        },
        "summary": summarise(results, modes, reference_mode),
        "questions": [
            {"id": q.id, "question": q.question, "type": q.type, "results": results[q.id]}
            for q in questions
        ],
    }


def summarise(
    results: dict[str, dict[str, dict[str, Any]]], modes: Sequence[str], reference_mode: str
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for mode in modes:
        rows = [by_mode[mode] for by_mode in results.values() if mode in by_mode]
        costs = [r["cost_usd"] for r in rows]
        recalls = [
            r["checks"].get(f"recall_of_{reference_mode}")
            for r in rows
            if r["checks"].get(f"recall_of_{reference_mode}") is not None
        ]
        summary[mode] = {
            "questions": len(rows),
            "passed_checks": sum(r["checks"]["passed"] for r in rows),
            "coverage_right": sum(r["checks"]["coverage_right"] for r in rows),
            "citations_hold": sum(r["checks"]["citations_hold"] for r in rows),
            "cost_usd": round(sum(costs), 4) if None not in costs else None,
            "mean_context_words": round(sum(r["context_words"] for r in rows) / max(len(rows), 1)),
            f"mean_recall_of_{reference_mode}": (
                round(sum(recalls) / len(recalls), 3) if recalls else None
            ),
        }
    return summary
