"""Contract tests for VectorIndex and Embedder. Every implementation must pass these.

To test a new adapter, add a factory to the matching IMPLEMENTATIONS: it gets a
temporary directory and returns a fresh, empty instance.
"""

import pytest

from askthe.adapters.memory import MemoryEmbedder, MemoryVectorIndex
from askthe.adapters.sqlite import SqliteVectorIndex
from askthe.core.interfaces import DocKind, Embedder, VectorIndex, VectorItem
from tests import factories as f

IMPLEMENTATIONS = {
    "memory": lambda tmp: MemoryVectorIndex(),
    "sqlite": lambda tmp: SqliteVectorIndex(tmp / "vectors.db"),
}


@pytest.fixture(params=list(IMPLEMENTATIONS))
def index(request, tmp_path) -> VectorIndex:
    return IMPLEMENTATIONS[request.param](tmp_path)


def item(doc_id, vector, video="v1", kind=DocKind.SEGMENT, creator=f.CREATOR, h="h"):
    return VectorItem(
        id=doc_id, kind=kind, creator_id=creator, video_id=video, content_hash=h, vector=vector
    )


def test_nearest_first_filtered_by_creator_and_kind(index):
    assert isinstance(index, VectorIndex)
    index.upsert(
        [
            item("near", [1.0, 0.1, 0.0]),
            item("far", [0.0, 1.0, 0.0]),
            item("profile", [1.0, 0.0, 0.0], kind=DocKind.PROFILE),
            item("other", [1.0, 0.0, 0.0], creator="someone-else"),
        ]
    )
    hits = index.search([1.0, 0.0, 0.0], f.CREATOR, [DocKind.SEGMENT], limit=10)
    assert [h.doc_id for h in hits] == ["near", "far"]
    assert hits[0].score > hits[1].score
    assert index.search([1, 0, 0], f.CREATOR, [DocKind.SEGMENT], limit=1)[0].doc_id == "near"


def test_hashes_upsert_and_removal(index):
    index.upsert([item("a", [1, 0], h="h1"), item("b", [0, 1], video="v2")])
    assert index.content_hashes("v1") == {"a": "h1"}
    index.upsert([item("a", [0, 1], h="h2")])
    assert index.content_hashes("v1") == {"a": "h2"}
    index.remove(["a"])
    assert index.content_hashes("v1") == {}
    index.remove_video("v2")
    assert index.search([0, 1], f.CREATOR, list(DocKind), limit=5) == []


def test_memory_embedder_puts_shared_words_closer():
    e = MemoryEmbedder()
    assert isinstance(e, Embedder)
    boots, also_boots, denim = e.embed(["warm winter boots", "boots for winter", "raw denim"])
    index = MemoryVectorIndex()
    index.upsert([item("b", also_boots), item("d", denim)])
    assert index.search(boots, f.CREATOR, [DocKind.SEGMENT], limit=1)[0].doc_id == "b"
