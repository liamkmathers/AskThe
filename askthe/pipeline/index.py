"""Stage 4: build the keyword and vector indexes from segments and profiles.

Keyword documents are rebuilt for each video. Embeddings are only computed for
documents whose text (or embedder) changed since last time, so re-indexing is cheap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from askthe.core.chunking import content_hash, video_documents
from askthe.core.interfaces import (
    Embedder,
    KnowledgeStore,
    SearchDoc,
    SearchIndex,
    VectorIndex,
    VectorItem,
)
from askthe.core.models import Creator


@dataclass
class IndexReport:
    videos: int = 0
    documents: int = 0
    embedded: int = 0
    unchanged: int = 0
    unprofiled: list[str] = field(default_factory=list)


def index_videos(
    creator: Creator,
    store: KnowledgeStore,
    search: SearchIndex,
    vectors: VectorIndex,
    embedder: Embedder,
    on_progress: Callable[[str, str], None] = lambda video_id, status: None,
) -> IndexReport:
    report = IndexReport()
    entities = {e.id: e for e in store.list_entities(creator.slug)}
    pending: list[tuple[SearchDoc, str]] = []
    for video in store.list_videos(creator.slug):
        profile = store.get_profile(video.id)
        if profile is None:
            report.unprofiled.append(video.id)
        video_entities = [
            entities[i] for i in (profile.entity_ids if profile else []) if i in entities
        ]
        docs = video_documents(video, profile, store.get_segments(video.id), video_entities)

        search.remove_video(video.id)
        search.index(docs)

        known = vectors.content_hashes(video.id)
        current = {d.id for d in docs}
        stale = [doc_id for doc_id in known if doc_id not in current]
        if stale:
            vectors.remove(stale)
        for d in docs:
            h = content_hash(embedder.name, d.text)
            if known.get(d.id) == h:
                report.unchanged += 1
            else:
                pending.append((d, h))
        report.videos += 1
        report.documents += len(docs)
        on_progress(video.id, f"{len(docs)} documents" + ("" if profile else " (no profile yet)"))

    if pending:
        embedded = embedder.embed([d.text for d, _ in pending])
        vectors.upsert(
            [
                VectorItem(
                    id=d.id,
                    kind=d.kind,
                    creator_id=d.creator_id,
                    video_id=d.video_id,
                    content_hash=h,
                    vector=v,
                )
                for (d, h), v in zip(pending, embedded, strict=True)
            ]
        )
        report.embedded = len(pending)
    return report
