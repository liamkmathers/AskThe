"""Fetch viewers' comments into the raw archive, for collecting real fan questions (M4).

Like fetching videos: needs access to the platform, skips videos already done, keeps
going when one video fails, and stops after several failures in a row (likely
rate-limited). Comment authors are never stored.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from askthe.core.interfaces import CommentSource, RawArchive
from askthe.core.models import Creator, RawComments
from askthe.pipeline.fetch import FetchReport


def fetch_comments(
    creator: Creator,
    platform_ids: Sequence[str],
    source: CommentSource,
    archive: RawArchive,
    source_name: str,
    per_video: int = 300,
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
        if archive.has_comments(creator.slug, platform_id):
            report.skipped.append(platform_id)
            on_progress(platform_id, "skipped (comments already fetched)")
            continue
        if i and delay_s:
            time.sleep(delay_s)  # be polite to the platform
        try:
            comments = source.get_comments(platform_id, per_video)
            archive.save_comments(
                RawComments(
                    creator_slug=creator.slug,
                    platform_id=platform_id,
                    comments=comments,
                    fetched_at=datetime.now(UTC),
                    source=source_name,
                )
            )
        except Exception as e:  # noqa: BLE001 - report every failure, keep going
            first_line = next((line for line in str(e).splitlines() if line.strip()), "")
            report.failed[platform_id] = f"{type(e).__name__}: {first_line}"[:300]
            on_progress(platform_id, f"failed: {report.failed[platform_id]}")
            consecutive_failures += 1
            continue
        consecutive_failures = 0
        report.fetched.append(platform_id)
        on_progress(platform_id, f"{len(comments)} comments")
    return report
