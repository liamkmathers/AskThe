"""File-based adapters: the raw archive on disk, and transcripts from caption files."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from askthe.core.captions import parse_cues
from askthe.core.models import RawVideo, Transcript, TranscriptKind


class FileRawArchive:
    """Raw videos as JSON at <root>/<creator>/raw/<platform_id>.json. Never overwritten."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _dir(self, creator_slug: str) -> Path:
        return self._root / creator_slug / "raw"

    def _path(self, creator_slug: str, platform_id: str) -> Path:
        return self._dir(creator_slug) / f"{platform_id}.json"

    def has(self, creator_slug: str, platform_id: str) -> bool:
        return self._path(creator_slug, platform_id).exists()

    def save(self, raw: RawVideo) -> None:
        path = self._path(raw.creator_slug, raw.meta.platform_id)
        if path.exists():
            raise FileExistsError(f"{path} already exists; raw records are immutable")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so an interrupted save never leaves a partial file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(raw.model_dump_json(indent=2))
            os.link(tmp, path)  # fails if the file appeared meanwhile
        finally:
            os.unlink(tmp)

    def load(self, creator_slug: str, platform_id: str) -> RawVideo:
        path = self._path(creator_slug, platform_id)
        try:
            return RawVideo.model_validate_json(path.read_text())
        except FileNotFoundError:
            raise LookupError(f"no raw video at {path}") from None

    def list_ids(self, creator_slug: str) -> list[str]:
        directory = self._dir(creator_slug)
        if not directory.exists():
            return []
        return sorted(p.stem for p in directory.glob("*.json"))


class CaptionFileTranscriptSource:
    """Transcripts from caption files: <dir>/<platform_id>.vtt or .srt.

    For transcripts that come from somewhere other than YouTube's public captions,
    such as files a creator exports from YouTube Studio.
    """

    def __init__(self, directory: Path, kind: TranscriptKind, language: str = "en") -> None:
        self._dir = Path(directory)
        self._kind = kind
        self._language = language

    def get_transcript(self, platform_id: str) -> Transcript:
        for suffix in (".vtt", ".srt"):
            path = self._dir / f"{platform_id}{suffix}"
            if path.exists():
                fragments = parse_cues(path.read_text(encoding="utf-8-sig"))
                if not fragments:
                    raise ValueError(f"no captions found in {path}")
                return Transcript(kind=self._kind, language=self._language, fragments=fragments)
        raise LookupError(f"no .vtt or .srt caption file for {platform_id!r} in {self._dir}")
