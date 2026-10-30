"""Contract tests for KnowledgeStore. Every implementation must pass these.

To test a new store adapter, add a factory to IMPLEMENTATIONS: it gets a temporary
directory and returns a fresh, empty store.
"""

from datetime import UTC, datetime

import pytest

from askthe.adapters.memory import MemoryKnowledgeStore
from askthe.adapters.sqlite import SqliteKnowledgeStore
from askthe.core import ids
from askthe.core.interfaces import KnowledgeStore
from askthe.core.models import AnswerLog, Coverage, ProductVersion, VideoProfile, VideoType
from tests import factories as f

IMPLEMENTATIONS = {
    "memory": lambda tmp: MemoryKnowledgeStore(),
    "sqlite": lambda tmp: SqliteKnowledgeStore(tmp / "store.db"),
}


@pytest.fixture(params=list(IMPLEMENTATIONS))
def store(request, tmp_path) -> KnowledgeStore:
    return IMPLEMENTATIONS[request.param](tmp_path)


def test_implements_interface(store):
    assert isinstance(store, KnowledgeStore)


def test_videos_upsert_and_list_by_creator_in_date_order(store):
    newer = f.video("b", published_at=datetime(2025, 6, 1, tzinfo=UTC))
    older = f.video("a", published_at=datetime(2024, 1, 1, tzinfo=UTC))
    other = f.video("c", creator_slug="someone-else")
    for v in (newer, older, other):
        store.upsert_video(v)
    assert [v.platform_id for v in store.list_videos(f.CREATOR)] == ["a", "b"]

    store.upsert_video(newer.model_copy(update={"title": "Renamed"}))
    assert store.get_video(newer.id).title == "Renamed"
    assert store.get_video("missing") is None


def test_segments_are_replaced_per_video_and_ordered(store):
    vid = f.video().id
    store.replace_segments(vid, [f.segment(vid, 1), f.segment(vid, 0)])
    assert [s.id for s in store.get_segments(vid)] == [
        ids.segment_id(vid, 0),
        ids.segment_id(vid, 1),
    ]
    store.replace_segments(vid, [f.segment(vid, 0, text="rebuilt")])
    assert [s.text for s in store.get_segments(vid)] == ["rebuilt"]
    assert store.get_segment(ids.segment_id(vid, 1)) is None
    assert store.get_segment(ids.segment_id(vid, 0)).text == "rebuilt"


def test_records_for_another_video_are_rejected(store):
    vid = f.video("a").id
    with pytest.raises(ValueError):
        store.replace_segments(vid, [f.segment(f.video("b").id)])
    with pytest.raises(ValueError):
        store.replace_claims(vid, [f.claim(f.video("b").id)])


def test_profiles(store):
    vid = f.video().id
    profile = VideoProfile(
        video_id=vid,
        purpose="Rank t-shirts for value",
        video_type=VideoType.RANKING,
        thesis="Price unlocks quality, up to a point",
        profiler_version="t",
        model="m",
    )
    store.save_profile(profile)
    assert store.get_profile(vid) == profile
    assert store.get_profile("missing") is None


def test_entities_and_versions(store):
    fleece = f.entity("Patagonia Retro-X")
    store.upsert_entity(fleece)
    store.upsert_entity(f.entity("Other", creator_slug="someone-else"))
    assert store.list_entities(f.CREATOR) == [fleece]
    assert store.get_entity(fleece.id) == fleece

    vintage = ProductVersion(
        id=ids.version_id(fleece.id, "vintage"),
        entity_id=fleece.id,
        label="Vintage",
        era="1988",
        made_in="USA",
    )
    store.upsert_version(vintage)
    assert store.list_versions(fleece.id) == [vintage]


def test_claims_replace_per_video_and_query_by_entity(store):
    a, b = f.video("a").id, f.video("b").id
    eid = f.entity().id
    store.replace_claims(a, [f.claim(a, 0, entity_ids=[eid]), f.claim(a, 1)])
    store.replace_claims(b, [f.claim(b, 0, entity_ids=[eid])])
    assert {c.id for c in store.get_claims_for_entity(eid)} == {
        ids.claim_id(a, 0),
        ids.claim_id(b, 0),
    }
    store.replace_claims(a, [])
    assert [c.id for c in store.get_claims_for_entity(eid)] == [ids.claim_id(b, 0)]
    assert store.get_claims_for_video(a) == []


def test_answer_log(store):
    log = AnswerLog(
        id="1",
        creator_id=f.CREATOR,
        asked_at=datetime(2026, 1, 1, tzinfo=UTC),
        question="q",
        answer="a",
        covered=Coverage.NONE,
    )
    store.log_answer(log)
    assert store.list_answers(f.CREATOR) == [log]
    assert store.list_answers("someone-else") == []
    assert store.get_answer("1") == log and store.get_answer("missing") is None
    flagged = log.model_copy(update={"flagged": ["wrong date"]})
    store.log_answer(flagged)  # saving again replaces
    assert store.list_answers(f.CREATOR) == [flagged]
