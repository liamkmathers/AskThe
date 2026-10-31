"""Importing a creator's own written items (posts, articles) from a data export they
downloaded and handed over (D29). A stage-1 alternative to fetching: the items go into
the raw archive, and `segment` and `index` then treat them like videos.

Items already imported are skipped, so importing a newer export of the same account
adds only what's new and never changes what was saved (raw data is never modified).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from askthe.core.interfaces import ExportSource, RawArchive
from askthe.core.models import Creator


@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)  # in the raw archive from before
    skipped: dict[str, str] = field(default_factory=dict)  # left out of the export, and why


def import_export(
    creator: Creator,
    path: Path,
    source: ExportSource,
    archive: RawArchive,
    include_comments: bool = False,
    on_progress: Callable[[str, str], None] = lambda item_id, status: None,
) -> ImportReport:
    contents = source.read_export(creator, path, include_comments=include_comments)
    report = ImportReport(skipped=dict(contents.skipped))
    for raw in contents.items:
        if raw.creator_slug != creator.slug:
            raise ValueError(f"export item {raw.meta.platform_id} is for {raw.creator_slug}")
        platform_id = raw.meta.platform_id
        if archive.has(creator.slug, platform_id):
            report.already.append(platform_id)
            on_progress(platform_id, "skipped (already imported)")
            continue
        archive.save(raw)
        report.imported.append(platform_id)
        on_progress(platform_id, f"imported {raw.meta.medium or 'item'}: {raw.meta.title}")
    return report
