"""Stage 2: rebuild videos and segments from the raw archive. Run `index` afterwards.

Everything written here is derived, so it is replaced on each run: re-running after
changing the segmenting rules gives the same result as a fresh database. Saved profiles
are restored when the segments they were made from are unchanged (D17); otherwise
they are stale and `understand` makes new ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from askthe.core.interfaces import KnowledgeStore, ProfileArchive, RawArchive
from askthe.core.models import Creator
from askthe.core.profiling import segments_fingerprint
from askthe.core.segmenting import SegmentingRules, segment_text, video_from_raw


@dataclass
class SegmentReport:
    videos: int = 0
    segments: int = 0
    restored: int = 0  # profiles restored from the profile archive
    stale: list[str] = field(default_factory=list)  # saved profiles whose segments changed


def segment_videos(
    creator: Creator,
    archive: RawArchive,
    store: KnowledgeStore,
    rules: SegmentingRules | None = None,
    profiles: ProfileArchive | None = None,
) -> SegmentReport:
    report = SegmentReport()
    for platform_id in archive.list_ids(creator.slug):
        raw = archive.load(creator.slug, platform_id)
        video = video_from_raw(raw)
        segments = segment_text(video.id, raw.transcript.text, rules)

        store.upsert_video(video)
        store.replace_segments(video.id, segments)
        saved = profiles.load(creator.slug, platform_id) if profiles else None
        if saved and saved.segments_fingerprint == segments_fingerprint(segments):
            for entity in saved.entities:
                store.upsert_entity(entity)
            store.save_profile(saved.profile)
            report.restored += 1
        elif saved:
            report.stale.append(platform_id)
        report.videos += 1
        report.segments += len(segments)
    return report
