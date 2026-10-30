"""HTTP API and pages for asking creators' videos (docs/UI_PLAN.md): a catalog of
creators, each creator's ask page, and a page per answer.

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
from askthe.core.ids import video_id
from askthe.core.interfaces import LLMError
from askthe.core.models import AnswerLog, BioCitation, BioItem, Creator
from askthe.pipeline.ask import RetrievalSettings, answerable_videos, ask, newer_videos
from askthe.wiring import Services

STATIC = Path(__file__).parent / "static"


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    parent_id: str | None = None  # the answer this follows up; unused by the v1 page


class FlagRequest(BaseModel):
    note: str = Field(default="", max_length=1000)


class UpdatesRequest(BaseModel):
    ids: list[str] = Field(max_length=50)


# Paths a creator slug can't take: the page's own routes.
RESERVED = {"static", "api", "a"}


def creator_card(creator: Creator, videos: int) -> dict[str, Any]:
    """What the catalog shows for a creator, all from its config and channel info."""
    channel = creator.channel
    return {
        "slug": creator.slug,
        "name": creator.instance_name,
        "display_name": creator.display_name,
        "tagline": creator.tagline,
        "avatar": channel.avatar_url if channel else None,
        "videos": videos,
    }


def create_app(
    services: Services, creators: dict[str, Creator], settings: RetrievalSettings
) -> FastAPI:
    """One app for every creator given: a catalog at `/`, each creator's ask page at
    `/<slug>`, and answer pages at `/a/<id>` (each answer knows its creator)."""
    reserved = RESERVED & set(creators)
    if reserved:
        raise ValueError(f"creator slugs clash with the page's routes: {sorted(reserved)}")
    app = FastAPI(title="Ask", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    store = services.store

    def page(status_code: int = 200) -> FileResponse:
        return FileResponse(STATIC / "index.html", status_code=status_code)

    def get_creator(slug: str) -> Creator:
        if slug not in creators:
            raise HTTPException(404, "no such creator")
        return creators[slug]

    def video_count(creator: Creator) -> int:
        return len(answerable_videos(creator, store, settings))

    @app.get("/api/creators")
    def catalog() -> list[dict[str, Any]]:
        return [creator_card(c, video_count(c)) for c in creators.values()]

    @app.get("/api/creators/{slug}")
    def creator_info(slug: str) -> dict[str, Any]:
        creator = get_creator(slug)
        bio = creator.bio

        def item(i: BioItem) -> dict[str, Any]:
            return {
                "title": i.title,
                "text": i.text,
                "when": i.when,
                "citations": [cite(c) for c in i.citations],
            }

        def cite(c: BioCitation) -> dict[str, Any]:
            video = store.get_video(video_id(creator.slug, c.video_id))
            return {
                "quote": c.quote,
                "url": watch_url(creator.platform, c.video_id),
                "title": video.title if video else None,
                "published": video.published_at.date().isoformat() if video else None,
            }

        links = [link.model_dump() for link in creator.links] or [
            {"label": "Channel", "url": creator.channel_url}
        ]
        return creator_card(creator, video_count(creator)) | {
            "refer_to": creator.refer_to_creator_as,
            "pronoun": creator.pronoun,
            # Who the creator is: the bio when one has been made, else the config's line.
            "summary": bio.summary if bio else creator.about,
            "journey": [item(i) for i in bio.journey] if bio else [],
            "ventures": [item(i) for i in bio.ventures] if bio else [],
            "links": links,
            "categories": creator.categories,
            "starters": creator.starter_questions,
        }

    @app.post("/api/creators/{slug}/ask")
    def ask_question(slug: str, request: AskRequest) -> StreamingResponse:
        creator = get_creator(slug)
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
        """An answer, only if it belongs to a creator this app serves."""
        log = store.get_answer(answer_id)
        if log is None or log.creator_id not in creators:
            raise HTTPException(404, "no such answer")
        return log

    @app.get("/api/answers/{answer_id}")
    def get_answer(answer_id: str) -> dict[str, Any]:
        log = load(answer_id)
        creator = creators[log.creator_id]
        return snapshot(log, newer_videos(creator, log, store, services.search, settings))

    @app.post("/api/answers/updates")
    def updates(request: UpdatesRequest) -> dict[str, dict[str, Any]]:
        """For the "Your questions" list: each answer's creator, and how many new
        videos match it. Answers this app doesn't serve are left out."""
        found = {}
        for answer_id in request.ids:
            log = store.get_answer(answer_id)
            if log and log.creator_id in creators:
                creator = creators[log.creator_id]
                newer = newer_videos(creator, log, store, services.search, settings)
                found[answer_id] = {"creator": log.creator_id, "new": len(newer)}
        return found

    @app.post("/api/answers/{answer_id}/flag")
    def flag(answer_id: str, request: FlagRequest) -> dict[str, bool]:
        log = load(answer_id)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        log.flagged.append(f"{stamp} {request.note.strip()}".strip())
        store.log_answer(log)
        return {"ok": True}

    def snapshot(log: AnswerLog, newer: list[Any]) -> dict[str, Any]:
        platform = creators[log.creator_id].platform
        return {
            "id": log.id,
            "creator": log.creator_id,
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
                    "url": watch_url(platform, v.platform_id),
                }
                for v in newer
            ],
        }

    # Pages last, so the API and static routes above win. Every page is the same
    # HTML; the script picks the view from the path.
    app.get("/", include_in_schema=False)(lambda: page())
    app.get("/a/{answer_id}", include_in_schema=False)(lambda answer_id: page())

    @app.get("/{slug}", include_in_schema=False)
    def creator_page(slug: str) -> FileResponse:
        return page(200 if slug in creators else 404)

    @app.get("/{slug}/{tab}", include_in_schema=False)
    def creator_tab(slug: str, tab: str) -> FileResponse:
        return page(200 if slug in creators and tab in ("about", "questions") else 404)

    return app
