"""Search documents for a video: contextual chunks, its profile, and its questions.

A chunk is a transcript segment plus a short header saying where it comes from (video,
date, section, and whether it overlaps a sponsor read or aside), so it can be found
and judged on its own: "it's way warmer" means nothing without knowing the video and
section it sits in.

Pure functions only: no I/O.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from askthe.core.interfaces import DocKind, SearchDoc
from askthe.core.models import Entity, Segment, Video, VideoProfile
from askthe.core.profiling import profile_search_text


def chunk_header(video: Video, profile: VideoProfile | None, index: int) -> str:
    parts = [f"{video.title} ({video.published_at.date().isoformat()})"]
    if profile:
        for section in profile.outline:
            if section.first_segment <= index <= section.last_segment:
                parts.append(f"Section: {section.title}. {section.summary}".strip())
                break
        for p in profile.passages:
            if p.first_segment <= index <= p.last_segment:
                parts.append(f"Contains {p.role.value}: {p.note}".strip(": "))
    return " | ".join(parts)


def video_documents(
    video: Video,
    profile: VideoProfile | None,
    segments: Sequence[Segment],
    entities: Sequence[Entity] = (),
) -> list[SearchDoc]:
    def doc(doc_id: str, kind: DocKind, text: str) -> SearchDoc:
        return SearchDoc(
            id=doc_id, kind=kind, creator_id=video.creator_id, video_id=video.id, text=text
        )

    docs = [
        doc(s.id, DocKind.SEGMENT, f"{chunk_header(video, profile, s.index)}\n{s.text}")
        for s in segments
    ]
    if profile:
        docs.append(
            doc(
                f"{video.id}:profile",
                DocKind.PROFILE,
                profile_search_text(video, profile, entities),
            )
        )
        docs += [
            doc(f"{video.id}:q{i:03d}", DocKind.PROFILE_QUESTION, q)
            for i, q in enumerate(profile.answers_questions)
        ]
    return docs


def content_hash(embedder_name: str, text: str) -> str:
    return hashlib.sha256(f"{embedder_name}\n{text}".encode()).hexdigest()
