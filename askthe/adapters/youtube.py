"""YouTube adapters: yt-dlp for the catalogue, metadata and comments,
youtube-transcript-api for transcripts.

YouTube blocks many cloud and datacenter IPs as bots. If fetching fails with a bot
or sign-in error, run `askthe fetch` from a home connection; every later stage works
offline from the saved raw files. See docs/RISKS_AND_QUESTIONS.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from askthe.core.models import (
    Comment,
    Creator,
    Transcript,
    TranscriptKind,
    VideoListing,
    VideoMeta,
)

WATCH_URL = "https://www.youtube.com/watch?v={}"


class FetchError(Exception):
    pass


class YtDlpCatalogSource:
    def __init__(self) -> None:
        import yt_dlp

        self._yt_dlp = yt_dlp

    def list_videos(self, creator: Creator) -> list[VideoListing]:
        url = creator.channel_url.rstrip("/") + "/videos"
        info = self._extract(url, extract_flat="in_playlist")
        return [
            VideoListing(
                platform_id=e["id"], title=e.get("title") or "", duration_s=e.get("duration")
            )
            for e in info.get("entries") or []
            if e and e.get("id")
        ]

    def get_video(self, creator: Creator, platform_id: str) -> VideoMeta:
        return meta_from_info(self._extract(WATCH_URL.format(platform_id)))

    def _extract(self, url: str, **options: Any) -> dict[str, Any]:
        return _extract(self._yt_dlp, url, **options)


class YtDlpCommentSource:
    """Top comments (YouTube's "top" order), without replies: fans' questions are
    nearly always top-level, and replies multiply the requests made."""

    def __init__(self) -> None:
        import yt_dlp

        self._yt_dlp = yt_dlp

    def get_comments(self, platform_id: str, limit: int) -> list[Comment]:
        info = _extract(
            self._yt_dlp,
            WATCH_URL.format(platform_id),
            getcomments=True,
            # max-comments, max-parents, max-replies
            extractor_args={
                "youtube": {"comment_sort": ["top"], "max_comments": [str(limit), "all", "0"]}
            },
        )
        return [comment_from_info(c) for c in info.get("comments") or [] if c.get("id")][:limit]


def comment_from_info(c: dict[str, Any]) -> Comment:
    """Map a yt-dlp comment dict to Comment. The author is deliberately dropped."""
    return Comment(
        id=c["id"],
        text=c.get("text") or "",
        like_count=c.get("like_count") or 0,
        is_reply=(c.get("parent") or "root") != "root",
        by_creator=bool(c.get("author_is_uploader")),
        published_at=datetime.fromtimestamp(c["timestamp"], tz=UTC) if c.get("timestamp") else None,
    )


def _extract(yt_dlp: Any, url: str, **options: Any) -> dict[str, Any]:
    params = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "logger": _QuietLogger(),  # errors are raised as FetchError instead
        **options,
    }
    try:
        with yt_dlp.YoutubeDL(params) as ydl:
            return ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise FetchError(str(e)) from None


class _QuietLogger:
    def debug(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None: ...

    def error(self, msg: str) -> None: ...


def meta_from_info(info: dict[str, Any]) -> VideoMeta:
    """Map a yt-dlp info dict to VideoMeta."""
    if info.get("timestamp"):
        published = datetime.fromtimestamp(info["timestamp"], tz=UTC)
    elif info.get("upload_date"):
        published = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=UTC)
    else:
        raise FetchError(f"no publish date for video {info.get('id')!r}")
    return VideoMeta(
        platform_id=info["id"],
        title=info.get("title") or "",
        description=info.get("description") or "",
        published_at=published,
        duration_s=float(info.get("duration") or 0),
        chapters=[c.get("title") or "" for c in info.get("chapters") or []],
        tags=list(info.get("tags") or []),
        view_count=info.get("view_count"),
        thumbnail_url=info.get("thumbnail"),
    )


class TranscriptApiSource:
    """Prefers creator-uploaded captions over auto-generated ones, in the given languages."""

    def __init__(self, languages: Sequence[str] = ("en",)) -> None:
        from youtube_transcript_api import YouTubeTranscriptApi

        self._api = YouTubeTranscriptApi()
        self._languages = list(languages)

    def get_transcript(self, platform_id: str) -> Transcript:
        from youtube_transcript_api import YouTubeTranscriptApiException

        try:
            listing = self._api.list(platform_id)
            fetched = listing.find_transcript(self._languages).fetch()
        except YouTubeTranscriptApiException as e:
            raise FetchError(f"{type(e).__name__}: {e}") from None
        return transcript_from_fetched(fetched)


def transcript_from_fetched(fetched: Any) -> Transcript:
    """Map a youtube-transcript-api FetchedTranscript to Transcript. Timing is dropped."""
    return Transcript(
        kind=TranscriptKind.AUTO if fetched.is_generated else TranscriptKind.MANUAL,
        language=fetched.language_code,
        text=" ".join(" ".join(s.text.split()) for s in fetched.snippets),
    )
