"""Small builders for valid domain records, so tests only spell out what they care about."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from askthe.core import ids
from askthe.core.models import (
    CaptionFragment,
    Claim,
    ClaimKind,
    Creator,
    Entity,
    EntityType,
    RawVideo,
    Segment,
    Transcript,
    TranscriptKind,
    Video,
    VideoMeta,
)

CREATOR = "test-creator"


def creator(**over: Any) -> Creator:
    fields: dict[str, Any] = dict(
        slug=CREATOR,
        display_name="Test Creator",
        instance_name="Ask Test Creator",
        platform="youtube",
        channel_url="https://example.com/@test",
        niche="testing",
        refer_to_creator_as="Test Creator",
        pronoun="they",
        categories=["boots"],
    )
    return Creator(**(fields | over))


def meta(platform_id: str = "vid1", **over: Any) -> VideoMeta:
    fields: dict[str, Any] = dict(
        platform_id=platform_id,
        title=f"Video {platform_id}",
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        duration_s=600,
    )
    return VideoMeta(**(fields | over))


def transcript(*texts: str) -> Transcript:
    fragments = [
        CaptionFragment(start_s=i * 3.0, duration_s=3.0, text=t) for i, t in enumerate(texts)
    ]
    return Transcript(kind=TranscriptKind.AUTO, language="en", fragments=fragments)


def raw_video(platform_id: str = "vid1", creator_slug: str = CREATOR) -> RawVideo:
    return RawVideo(
        creator_slug=creator_slug,
        meta=meta(platform_id),
        transcript=transcript("hello", "world"),
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
    )


def video(platform_id: str = "vid1", creator_slug: str = CREATOR, **over: Any) -> Video:
    fields: dict[str, Any] = dict(
        id=ids.video_id(creator_slug, platform_id),
        creator_id=creator_slug,
        platform_id=platform_id,
        title=f"Video {platform_id}",
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        duration_s=600,
        transcript_kind=TranscriptKind.AUTO,
    )
    return Video(**(fields | over))


def segment(video_id: str, index: int = 0, text: str = "some words", **over: Any) -> Segment:
    fields: dict[str, Any] = dict(
        id=ids.segment_id(video_id, index),
        video_id=video_id,
        start_s=index * 30.0,
        end_s=index * 30.0 + 30.0,
        text=text,
    )
    return Segment(**(fields | over))


def entity(name: str = "Iron Ranger", creator_slug: str = CREATOR, **over: Any) -> Entity:
    fields: dict[str, Any] = dict(
        id=ids.entity_id(creator_slug, name),
        creator_id=creator_slug,
        type=EntityType.PRODUCT,
        canonical_name=name,
    )
    return Entity(**(fields | over))


def claim(video_id: str, index: int = 0, **over: Any) -> Claim:
    fields: dict[str, Any] = dict(
        id=ids.claim_id(video_id, index),
        video_id=video_id,
        segment_ids=[ids.segment_id(video_id, 0)],
        start_s=0.0,
        end_s=10.0,
        quote="these are great",
        kind=ClaimKind.VERDICT,
        statement="They say these are great.",
        extractor_version="test-1",
        model="memory",
    )
    return Claim(**(fields | over))
