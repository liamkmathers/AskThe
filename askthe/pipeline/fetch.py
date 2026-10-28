"""Stage 1: fetch metadata and transcripts into the raw archive.

Videos already archived are skipped, so fetching is safe to re-run after a failure.
One video failing doesn't stop the others, but several failures in a row usually mean
the platform is rate-limiting us, so the run stops rather than make that worse.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from askthe.core.interfaces import CatalogSource, RawArchive, TranscriptSource
from askthe.core.models import Creator, RawVideo


@dataclass
class FetchReport:
    fetched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    stopped_early: bool = False


def fetch_videos(
    creator: Creator,
    platform_ids: Sequence[str],
    catalog: CatalogSource,
    transcripts: TranscriptSource,
    archive: RawArchive,
    source: str,
    delay_s: float = 0.0,
    max_consecutive_failures: int | None = None,
    on_progress: Callable[[str, str], None] = lambda platform_id, status: None,
) -> FetchReport:
    report = FetchReport()
    consecutive_failures = 0
    for i, platform_id in enumerate(platform_ids):
        if max_consecutive_failures and consecutive_failures >= max_consecutive_failures:
            report.stopped_early = True
            break
        if archive.has(creator.slug, platform_id):
            report.skipped.append(platform_id)
            on_progress(platform_id, "skipped (already fetched)")
            continue
        if i and delay_s:
            time.sleep(delay_s)  # be polite to the platform
        try:
            raw = RawVideo(
                creator_slug=creator.slug,
                meta=catalog.get_video(creator, platform_id),
                transcript=transcripts.get_transcript(platform_id),
                fetched_at=datetime.now(UTC),
                source=source,
            )
            archive.save(raw)
        except Exception as e:  # noqa: BLE001 - report every failure, keep going
            first_line = next((line for line in str(e).splitlines() if line.strip()), "")
            report.failed[platform_id] = f"{type(e).__name__}: {first_line}"[:300]
            on_progress(platform_id, f"failed: {report.failed[platform_id]}")
            consecutive_failures += 1
            continue
        consecutive_failures = 0
        report.fetched.append(platform_id)
        on_progress(platform_id, f"fetched: {raw.meta.title}")
    return report
