"""The web app and the engine pieces it relies on: streamed progress, saved answer
snapshots, sponsored quotes marked in code, and "new video since you asked"."""

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from askthe.adapters.memory import (
    MemoryCatalogSource,
    MemoryCommentSource,
    MemoryProfileArchive,
    MemoryRawArchive,
    MemoryTranscriptSource,
)
from askthe.app.server import create_app
from askthe.core.answering import (
    AnswerDraft,
    CitationDraft,
    check_answer,
    partial_answer,
    sponsor_read_texts,
)
from askthe.core.interfaces import LLMTask
from askthe.core.models import Coverage, Passage, PassageRole
from askthe.core.retrieval import PassageScore, QueryPlan, RerankDraft
from askthe.pipeline.ask import RetrievalSettings, ask, newer_videos
from askthe.wiring import Services
from tests import factories as f
from tests.test_retrieval import answer, build
from tests.test_wiring import config_with

QUESTION = "What keeps his feet warm in winter?"


def script(llm, draft=None):
    llm.script(LLMTask.PLAN, QueryPlan(queries=["warm winter boots"], names=[], broad=False))

    def rerank(context, prompt):
        parts = prompt.split("<passage n=")[1:]
        best = next(i for i, part in enumerate(parts) if "kept my feet warm" in part)
        return RerankDraft(scores=[PassageScore(n=best, score=3)])

    llm.script(LLMTask.RERANK, rerank)
    llm.script(LLMTask.ANSWER, draft or answer("boots", 1, "kept my feet warm in the snow"))


def test_partial_answer_decodes_the_answer_as_it_arrives():
    raw = json.dumps({"answer": 'He says "warm"\nand dry é [1]', "coverage": "full"})
    seen = [partial_answer(raw[:n]) for n in range(len(raw) + 1)]
    assert seen[0] == "" and seen[-1] == 'He says "warm"\nand dry é [1]'
    assert all(seen[i + 1].startswith(seen[i]) for i in range(len(seen) - 1))  # only grows


def test_quotes_inside_a_located_sponsor_read_are_marked_sponsored():
    video = f.video("abc")
    segments = [
        f.segment(video.id, 0, "I love these boots. This video is sponsored by Koio."),
        f.segment(video.id, 1, "Koio sneakers are my favorite, link below. Back to boots."),
    ]
    read = Passage(
        role=PassageRole.SPONSOR,
        first_segment=0,
        starts_with="This video is sponsored",
        last_segment=1,
        ends_with="link below",
    )
    reads = sponsor_read_texts(segments, [read])
    assert reads == ["This video is sponsored by Koio. Koio sneakers are my favorite, link below"]
    draft = AnswerDraft(
        answer="He loves the boots [1]; Koio are 'my favorite' [2].",
        coverage=Coverage.FULL,
        citations=[
            CitationDraft(n=1, video="abc", segment=0, quote="I love these boots"),
            CitationDraft(n=2, video="abc", segment=1, quote="Koio sneakers are my favorite"),
        ],
    )
    checked = check_answer(draft, {"abc": (video, segments)}, "youtube", {"abc": reads})
    assert [(s.n, s.sponsored) for s in checked.sources] == [(1, False), (2, True)]


def test_ask_streams_progress_and_saves_a_snapshot():
    store, search, llm, vectors, embedder = build()
    script(llm)
    events = []
    result = ask(
        f.creator(),
        QUESTION,
        store,
        search,
        llm,
        vectors=vectors,
        embedder=embedder,
        on_event=lambda kind, data: events.append((kind, data)),
        parent_id="earlier",
    )
    kinds = [k for k, _ in events]
    assert kinds[0] == "searching" and kinds[1] == "reading" and "writing" in kinds
    assert events[1][1]["videos"][0]["title"] == "All about boots"
    writes = [d["text"] for k, d in events if k == "writing"]
    assert writes[-1] == "He keeps warm in Red Wings [1]."
    saved = store.get_answer(result.answer_id)
    assert saved.question == QUESTION and saved.parent_id == "earlier"
    assert [s.quote for s in saved.sources] == ["kept my feet warm in the snow"]
    assert saved.videos_read == ["test-creator:boots"]


def test_newer_videos_are_the_matching_ones_published_after_the_answer():
    store, search, llm, vectors, embedder = build()
    script(llm)
    result = ask(f.creator(), QUESTION, store, search, llm, vectors=vectors, embedder=embedder)
    saved = store.get_answer(result.answer_id)
    assert newer_videos(f.creator(), saved, store, search) == []
    earlier = saved.model_copy(update={"asked_at": datetime(2020, 1, 1, tzinfo=UTC)})
    assert [v.platform_id for v in newer_videos(f.creator(), earlier, store, search)] == [
        "boots"
    ]  # the denim video doesn't match the question
    later = saved.model_copy(update={"asked_at": datetime.now(UTC) + timedelta(days=1)})
    assert newer_videos(f.creator(), later, store, search) == []


def client(tmp_path, llm_draft=None):
    store, search, llm, vectors, embedder = build()
    script(llm, llm_draft)
    services = Services(
        config=config_with(tmp_path, {"store": "memory"}),  # only the config is used
        catalog=MemoryCatalogSource(),
        transcripts=MemoryTranscriptSource(),
        comments=MemoryCommentSource(),
        raw_archive=MemoryRawArchive(),
        profiles=MemoryProfileArchive(),
        store=store,
        search=search,
        embedder=embedder,
        vectors=vectors,
        llm=llm,
    )
    creator = f.creator(starter_questions=["Best boots for snow?"])
    return TestClient(create_app(services, creator, RetrievalSettings())), store


def stream(response):
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_app_asks_streams_and_serves_the_saved_answer(tmp_path):
    app, store = client(tmp_path)
    info = app.get("/api/creator").json()
    assert info["name"] == "Ask Test Creator" and info["starters"] == ["Best boots for snow?"]
    assert app.get("/").status_code == 200 and "<main" in app.get("/").text
    assert "app.js" in app.get("/a/anything").text  # answer pages are the same page

    events = stream(app.post("/api/ask", json={"question": QUESTION}))
    types = [e["type"] for e in events]
    assert types[0] == "searching" and types[-1] == "done" and "writing" in types
    done = events[-1]["answer"]
    assert done["coverage"] == "full" and done["sources"][0]["sponsored"] is False
    assert done["sources"][0]["url"] == "https://www.youtube.com/watch?v=boots"

    fetched = app.get(f"/api/answers/{done['id']}").json()
    assert fetched["answer"] == done["answer"] and fetched["newer_videos"] == []
    assert app.post("/api/answers/updates", json={"ids": [done["id"], "nope"]}).json() == {
        done["id"]: 0
    }
    assert app.post(f"/api/answers/{done['id']}/flag", json={"note": "wrong year"}).json()
    assert store.get_answer(done["id"]).flagged[0].endswith("wrong year")
    assert app.get("/api/answers/nope").status_code == 404


def test_app_rejects_empty_questions_and_reports_model_failures(tmp_path):
    app, _ = client(tmp_path)
    assert app.post("/api/ask", json={"question": "a"}).status_code == 422

    broken, _ = client(tmp_path)
    broken.post("/api/ask", json={"question": QUESTION})  # uses up the scripted answer
    events = stream(broken.post("/api/ask", json={"question": QUESTION}))
    assert events[-1]["type"] == "error" and events[-1]["message"]


def test_unprofiled_videos_are_left_out_when_profiles_are_required():
    from askthe.core.models import VideoProfile, VideoType
    from askthe.core.profiling import PROFILER_VERSION
    from askthe.pipeline.ask import answerable_videos

    store, search, llm, vectors, embedder = build()  # "boots" and "denim", unprofiled
    store.save_profile(
        VideoProfile(
            video_id=f.video("denim").id,
            purpose="p",
            video_type=VideoType.REVIEW,
            thesis="t",
            profiler_version=PROFILER_VERSION,
            model="m",
        )
    )
    required = RetrievalSettings(require_profiles=True)
    assert [v.platform_id for v in answerable_videos(f.creator(), store, required)] == ["denim"]
    assert len(answerable_videos(f.creator(), store, RetrievalSettings())) == 2

    llm.script(LLMTask.PLAN, QueryPlan(queries=["warm winter boots"], names=[], broad=False))
    llm.script(LLMTask.RERANK, RerankDraft(scores=[]))
    llm.script(
        LLMTask.ANSWER, AnswerDraft(answer="Not covered.", coverage=Coverage.NONE, citations=[])
    )
    result = ask(
        f.creator(),
        QUESTION,
        store,
        search,
        llm,
        vectors=vectors,
        embedder=embedder,
        settings=required,
    )
    assert "test-creator:boots" not in result.videos_read  # its passages never reach the model
    reranked = [c[2] for c in llm.calls if c[0] is LLMTask.RERANK]
    assert reranked and "kept my feet warm" not in reranked[0] and "Raw denim" in reranked[0]
