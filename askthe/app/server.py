"""HTTP API and page for asking a creator's videos (docs/UI_PLAN.md).

The app is handed ready-built services (askthe/wiring.py builds them); it never
constructs adapters. Answering runs in a worker thread and its progress is streamed
to the page as newline-delimited JSON: searching, reading, writing (the answer so
far), retrying, then done with the verified answer, or error.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from askthe.core.answering import watch_url
from askthe.core.interfaces import LLMError
from askthe.core.models import AnswerLog, Creator
from askthe.pipeline.ask import RetrievalSettings, ask, newer_videos
from askthe.wiring import Services

STATIC = Path(__file__).parent / "static"


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    parent_id: str | None = None  # the answer this follows up; unused by the v1 page


class FlagRequest(BaseModel):
    note: str = Field(default="", max_length=1000)


class UpdatesRequest(BaseModel):
    ids: list[str] = Field(max_length=50)


def create_app(services: Services, creator: Creator, settings: RetrievalSettings) -> FastAPI:
    app = FastAPI(title=creator.instance_name, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    store = services.store

    def page() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.get("/", include_in_schema=False)(page)
    app.get("/a/{answer_id}", include_in_schema=False)(lambda answer_id: page())

    @app.get("/api/creator")
    def creator_info() -> dict[str, Any]:
        return {
            "name": creator.instance_name,
            "refer_to": creator.refer_to_creator_as,
            "pronoun": creator.pronoun,
            "niche": creator.niche,
            "categories": creator.categories,
            "starters": creator.starter_questions,
            "videos": len(store.list_videos(creator.slug)),
        }

    @app.post("/api/ask")
    def ask_question(request: AskRequest) -> StreamingResponse:
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def work() -> None:
            try:
                result = ask(
                    creator,
                    request.question.strip(),
                    store,
                    services.search,
                    services.llm,
                    vectors=services.vectors,
                    embedder=services.embedder,
                    settings=settings,
                    on_event=lambda kind, data: events.put({"type": kind, **data}),
                    parent_id=request.parent_id,
                )
                log = store.get_answer(result.answer_id) if result.answer_id else None
                if log is None:
                    raise RuntimeError("the answer was not saved")
                events.put({"type": "done", "answer": snapshot(log, [])})
            except LLMError as e:
                events.put({"type": "error", "message": f"The model couldn't answer: {e}"})
            except Exception:  # noqa: BLE001 - the page gets a message, the log a trace
                import traceback

                traceback.print_exc()
                events.put({"type": "error", "message": "Something went wrong. Try again."})
            finally:
                events.put(None)

        threading.Thread(target=work, daemon=True).start()

        def stream() -> Iterator[str]:
            while (event := events.get()) is not None:
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    def load(answer_id: str) -> AnswerLog:
        log = store.get_answer(answer_id)
        if log is None or log.creator_id != creator.slug:
            raise HTTPException(404, "no such answer")
        return log

    @app.get("/api/answers/{answer_id}")
    def get_answer(answer_id: str) -> dict[str, Any]:
        log = load(answer_id)
        return snapshot(log, newer_videos(creator, log, store, services.search))

    @app.post("/api/answers/updates")
    def updates(request: UpdatesRequest) -> dict[str, int]:
        """For the "Your questions" list: how many new videos match each answer."""
        found = {}
        for answer_id in request.ids:
            log = store.get_answer(answer_id)
            if log and log.creator_id == creator.slug:
                found[answer_id] = len(newer_videos(creator, log, store, services.search))
        return found

    @app.post("/api/answers/{answer_id}/flag")
    def flag(answer_id: str, request: FlagRequest) -> dict[str, bool]:
        log = load(answer_id)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        log.flagged.append(f"{stamp} {request.note.strip()}".strip())
        store.log_answer(log)
        return {"ok": True}

    def snapshot(log: AnswerLog, newer: list[Any]) -> dict[str, Any]:
        return {
            "id": log.id,
            "question": log.question,
            "asked_at": log.asked_at.isoformat(),
            "answer": log.answer,
            "coverage": log.covered.value,
            "changed_mind": log.changed_mind,
            "sources": [s.model_dump(mode="json") for s in log.sources],
            "parent_id": log.parent_id,
            "newer_videos": [
                {
                    "title": v.title,
                    "published": v.published_at.date().isoformat(),
                    "url": watch_url(creator.platform, v.platform_id),
                }
                for v in newer
            ],
        }

    return app
