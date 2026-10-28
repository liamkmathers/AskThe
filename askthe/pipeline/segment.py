"""Stage 2: rebuild videos and segments from the raw archive, and index the segments.

Everything written here is derived, so it is replaced on each run: re-running after
changing the segmenting rules gives the same result as a fresh database.
"""

from __future__ import annotations

from dataclasses import dataclass

from askthe.core.interfaces import DocKind, KnowledgeStore, RawArchive, SearchDoc, SearchIndex
from askthe.core.models import Creator
from askthe.core.segmenting import SegmentingRules, segment_text, video_from_raw


@dataclass
class SegmentReport:
    videos: int = 0
    segments: int = 0


def segment_videos(
    creator: Creator,
    archive: RawArchive,
    store: KnowledgeStore,
    search: SearchIndex,
    rules: SegmentingRules | None = None,
) -> SegmentReport:
    report = SegmentReport()
    for platform_id in archive.list_ids(creator.slug):
        raw = archive.load(creator.slug, platform_id)
        video = video_from_raw(raw)
        segments = segment_text(video.id, raw.transcript.text, rules)

        store.upsert_video(video)
        store.replace_segments(video.id, segments)
        search.remove_video(video.id)
        search.index(
            [
                SearchDoc(
                    id=s.id,
                    kind=DocKind.SEGMENT,
                    creator_id=creator.slug,
                    video_id=video.id,
                    text=s.text,
                )
                for s in segments
            ]
        )
        report.videos += 1
        report.segments += len(segments)
    return report
