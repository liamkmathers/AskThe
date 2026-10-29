"""Profiles are saved outside the database and restored when it is rebuilt (D17).

Contract tests run against every ProfileArchive; add a factory to IMPLEMENTATIONS to
test a new adapter.
"""

import pytest

from askthe.adapters.files import FileProfileArchive
from askthe.adapters.memory import (
    MemoryKnowledgeStore,
    MemoryLLMClient,
    MemoryProfileArchive,
    MemoryRawArchive,
)
from askthe.core.interfaces import LLMTask, ProfileArchive
from askthe.core.models import ProfileRecord
from askthe.core.profiling import segments_fingerprint
from askthe.pipeline.segment import segment_videos
from askthe.pipeline.understand import understand_videos
from tests import factories as f
from tests.test_answering import creator, f_profile, profile_draft

IMPLEMENTATIONS = {
    "memory": lambda tmp: MemoryProfileArchive(),
    "files": lambda tmp: FileProfileArchive(tmp),
}


@pytest.fixture(params=list(IMPLEMENTATIONS))
def archive(request, tmp_path) -> ProfileArchive:
    return IMPLEMENTATIONS[request.param](tmp_path)


def record(platform_id="abc", thesis="t"):
    video_id = f.video(platform_id).id
    return ProfileRecord(
        platform_id=platform_id,
        profile=f_profile(video_id, thesis=thesis),
        entities=[f.entity("Uniqlo")],
        segments_fingerprint="0123",
    )


def test_archive_saves_loads_and_replaces(archive):
    assert isinstance(archive, ProfileArchive)
    assert archive.load(f.CREATOR, "abc") is None
    archive.save(f.CREATOR, record())
    assert archive.load(f.CREATOR, "abc") == record()
    archive.save(f.CREATOR, record(thesis="newer"))
    assert archive.load(f.CREATOR, "abc").profile.thesis == "newer"
    assert archive.list_ids(f.CREATOR) == ["abc"]
    assert archive.list_ids("someone-else") == []


def test_segment_fingerprint_changes_with_text_or_order():
    a = [f.segment("v", 0, "one"), f.segment("v", 1, "two")]
    assert segments_fingerprint(a) == segments_fingerprint(list(reversed(a)))
    assert segments_fingerprint(a) != segments_fingerprint([f.segment("v", 0, "one two")])


def rebuilt(raw, profiles):
    store = MemoryKnowledgeStore()
    report = segment_videos(creator(), raw, store, profiles=profiles)
    return store, report


def test_profiles_survive_a_database_rebuild_and_stale_ones_are_not_restored():
    raw, profiles = MemoryRawArchive(), MemoryProfileArchive()
    raw.save(f.raw_video("abc"))
    store, _ = rebuilt(raw, profiles)
    llm = MemoryLLMClient()
    llm.script(LLMTask.UNDERSTAND, profile_draft())
    understand_videos(creator(), store, llm, archive=profiles)
    video_id = f.video("abc").id
    made = store.get_profile(video_id)
    assert profiles.load(f.CREATOR, "abc").profile == made

    fresh, report = rebuilt(raw, profiles)
    assert report.restored == 1 and not report.stale
    assert fresh.get_profile(video_id) == made
    assert fresh.get_entity("test-creator:e:uniqlo").aliases == ["Unilo"]
    # Restored profiles are not paid for again.
    assert understand_videos(creator(), fresh, MemoryLLMClient(), archive=profiles).skipped

    saved = profiles.load(f.CREATOR, "abc")
    profiles.save(f.CREATOR, saved.model_copy(update={"segments_fingerprint": "changed"}))
    stale, report = rebuilt(raw, profiles)
    assert report.restored == 0 and report.stale == ["abc"]
    assert stale.get_profile(video_id) is None


def test_understand_saves_profiles_made_before_the_archive_existed():
    raw, profiles = MemoryRawArchive(), MemoryProfileArchive()
    raw.save(f.raw_video("abc"))
    store, _ = rebuilt(raw, None)
    llm = MemoryLLMClient()
    llm.script(LLMTask.UNDERSTAND, profile_draft())
    understand_videos(creator(), store, llm)  # no archive yet
    assert profiles.list_ids(f.CREATOR) == []
    report = understand_videos(creator(), store, MemoryLLMClient(), archive=profiles)
    assert report.skipped and profiles.list_ids(f.CREATOR) == ["abc"]
    assert profiles.load(f.CREATOR, "abc").entities
