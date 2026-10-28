"""Contract tests for RawArchive and SearchIndex. Every implementation must pass these.

To test a new adapter, add its factory to the matching IMPLEMENTATIONS list.
"""

import pytest

from askthe.adapters.memory import MemoryRawArchive, MemorySearchIndex
from askthe.core.interfaces import DocKind, RawArchive, SearchDoc, SearchIndex, SearchQuery
from tests import factories as f

RAW_IMPLEMENTATIONS = [MemoryRawArchive]
SEARCH_IMPLEMENTATIONS = [MemorySearchIndex]


@pytest.fixture(params=RAW_IMPLEMENTATIONS, ids=lambda cls: cls.__name__)
def archive(request) -> RawArchive:
    return request.param()


@pytest.fixture(params=SEARCH_IMPLEMENTATIONS, ids=lambda cls: cls.__name__)
def index(request) -> SearchIndex:
    return request.param()


# --- RawArchive -----------------------------------------------------------------


def test_archive_saves_and_loads(archive):
    assert isinstance(archive, RawArchive)
    raw = f.raw_video("abc")
    assert not archive.has(f.CREATOR, "abc")
    archive.save(raw)
    assert archive.has(f.CREATOR, "abc")
    assert archive.load(f.CREATOR, "abc") == raw
    assert archive.list_ids(f.CREATOR) == ["abc"]
    assert archive.list_ids("someone-else") == []


def test_archived_records_are_immutable(archive):
    archive.save(f.raw_video("abc"))
    with pytest.raises(FileExistsError):
        archive.save(f.raw_video("abc"))
    loaded = archive.load(f.CREATOR, "abc")
    loaded.meta.title = "tampered"
    assert archive.load(f.CREATOR, "abc").meta.title != "tampered"


def test_archive_missing_video_raises_lookup_error(archive):
    with pytest.raises(LookupError):
        archive.load(f.CREATOR, "missing")


# --- SearchIndex ----------------------------------------------------------------


def doc(doc_id: str, text: str, kind=DocKind.SEGMENT, video="v1", creator=f.CREATOR):
    return SearchDoc(id=doc_id, kind=kind, creator_id=creator, video_id=video, text=text)


def test_search_ranks_better_matches_first(index):
    assert isinstance(index, SearchIndex)
    index.index(
        [
            doc("1", "these boots are warm in winter"),
            doc("2", "warm jacket"),
            doc("3", "denim care"),
        ]
    )
    hits = index.search(SearchQuery(text="warm winter boots", creator_id=f.CREATOR))
    assert [h.doc_id for h in hits][:2] == ["1", "2"]
    assert "3" not in [h.doc_id for h in hits]


def test_search_filters_by_creator_and_kind(index):
    index.index(
        [
            doc("1", "warm boots"),
            doc("2", "warm boots", kind=DocKind.CLAIM),
            doc("3", "warm boots", creator="someone-else"),
        ]
    )
    hits = index.search(SearchQuery(text="warm boots", creator_id=f.CREATOR, kinds=[DocKind.CLAIM]))
    assert [h.doc_id for h in hits] == ["2"]


def test_search_remove_video_and_limit(index):
    index.index([doc(str(i), "warm boots", video=f"v{i % 2}") for i in range(6)])
    assert len(index.search(SearchQuery(text="warm", creator_id=f.CREATOR, limit=2))) == 2
    index.remove_video("v0")
    hits = index.search(SearchQuery(text="warm", creator_id=f.CREATOR))
    assert {h.video_id for h in hits} == {"v1"}


def test_reindexing_a_doc_replaces_it(index):
    index.index([doc("1", "warm boots")])
    index.index([doc("1", "denim")])
    assert index.search(SearchQuery(text="boots", creator_id=f.CREATOR)) == []
