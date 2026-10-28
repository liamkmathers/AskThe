"""In-memory implementations of every interface.

Used by unit tests (no network, API keys or database) and as the default wiring
until the real adapters land. Behaviour is deliberately simple but honours each
interface's contract.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from askthe.core.interfaces import (
    LLMTask,
    SearchDoc,
    SearchHit,
    SearchQuery,
    T,
)
from askthe.core.models import (
    AnswerLog,
    Claim,
    Creator,
    Entity,
    ProductVersion,
    RawVideo,
    Segment,
    Transcript,
    Video,
    VideoListing,
    VideoMeta,
    VideoProfile,
)


class MemoryCatalogSource:
    def __init__(self) -> None:
        self._videos: dict[str, dict[str, VideoMeta]] = defaultdict(dict)

    def add(self, creator_slug: str, meta: VideoMeta) -> None:
        self._videos[creator_slug][meta.platform_id] = meta

    def list_videos(self, creator: Creator) -> list[VideoListing]:
        videos = sorted(self._videos[creator.slug].values(), key=lambda m: m.published_at)
        return [
            VideoListing(platform_id=m.platform_id, title=m.title, duration_s=m.duration_s)
            for m in videos
        ]

    def get_video(self, creator: Creator, platform_id: str) -> VideoMeta:
        try:
            return self._videos[creator.slug][platform_id]
        except KeyError:
            raise LookupError(f"no video {platform_id!r} for {creator.slug!r}") from None


class MemoryTranscriptSource:
    def __init__(self) -> None:
        self._transcripts: dict[str, Transcript] = {}

    def add(self, platform_id: str, transcript: Transcript) -> None:
        self._transcripts[platform_id] = transcript

    def get_transcript(self, platform_id: str) -> Transcript:
        try:
            return self._transcripts[platform_id]
        except KeyError:
            raise LookupError(f"no transcript for {platform_id!r}") from None


class MemoryRawArchive:
    def __init__(self) -> None:
        self._raw: dict[tuple[str, str], RawVideo] = {}

    def has(self, creator_slug: str, platform_id: str) -> bool:
        return (creator_slug, platform_id) in self._raw

    def save(self, raw: RawVideo) -> None:
        key = (raw.creator_slug, raw.meta.platform_id)
        if key in self._raw:
            raise FileExistsError(f"raw video {key} already archived; raw records are immutable")
        self._raw[key] = raw.model_copy(deep=True)

    def load(self, creator_slug: str, platform_id: str) -> RawVideo:
        try:
            return self._raw[(creator_slug, platform_id)].model_copy(deep=True)
        except KeyError:
            raise LookupError(f"no raw video {platform_id!r} for {creator_slug!r}") from None

    def list_ids(self, creator_slug: str) -> list[str]:
        return sorted(pid for slug, pid in self._raw if slug == creator_slug)


class MemoryKnowledgeStore:
    def __init__(self) -> None:
        self._videos: dict[str, Video] = {}
        self._segments: dict[str, list[Segment]] = {}
        self._profiles: dict[str, VideoProfile] = {}
        self._entities: dict[str, Entity] = {}
        self._versions: dict[str, ProductVersion] = {}
        self._claims: dict[str, list[Claim]] = {}
        self._answers: list[AnswerLog] = []

    def upsert_video(self, video: Video) -> None:
        self._videos[video.id] = video

    def get_video(self, video_id: str) -> Video | None:
        return self._videos.get(video_id)

    def list_videos(self, creator_id: str) -> list[Video]:
        videos = [v for v in self._videos.values() if v.creator_id == creator_id]
        return sorted(videos, key=lambda v: v.published_at)

    def replace_segments(self, video_id: str, segments: Sequence[Segment]) -> None:
        _check_belongs(video_id, segments)
        self._segments[video_id] = sorted(segments, key=lambda s: s.index)

    def get_segments(self, video_id: str) -> list[Segment]:
        return list(self._segments.get(video_id, []))

    def get_segment(self, segment_id: str) -> Segment | None:
        for segments in self._segments.values():
            for segment in segments:
                if segment.id == segment_id:
                    return segment
        return None

    def save_profile(self, profile: VideoProfile) -> None:
        self._profiles[profile.video_id] = profile

    def get_profile(self, video_id: str) -> VideoProfile | None:
        return self._profiles.get(video_id)

    def upsert_entity(self, entity: Entity) -> None:
        self._entities[entity.id] = entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def list_entities(self, creator_id: str) -> list[Entity]:
        return [e for e in self._entities.values() if e.creator_id == creator_id]

    def upsert_version(self, version: ProductVersion) -> None:
        self._versions[version.id] = version

    def list_versions(self, entity_id: str) -> list[ProductVersion]:
        return [v for v in self._versions.values() if v.entity_id == entity_id]

    def replace_claims(self, video_id: str, claims: Sequence[Claim]) -> None:
        _check_belongs(video_id, claims)
        self._claims[video_id] = list(claims)

    def get_claims_for_video(self, video_id: str) -> list[Claim]:
        return list(self._claims.get(video_id, []))

    def get_claims_for_entity(self, entity_id: str) -> list[Claim]:
        return [
            claim
            for claims in self._claims.values()
            for claim in claims
            if entity_id in claim.entity_ids
        ]

    def log_answer(self, log: AnswerLog) -> None:
        self._answers.append(log)

    def list_answers(self, creator_id: str) -> list[AnswerLog]:
        return [a for a in self._answers if a.creator_id == creator_id]


def _check_belongs(video_id: str, records: Sequence[Segment | Claim]) -> None:
    stray = [r.id for r in records if r.video_id != video_id]
    if stray:
        raise ValueError(f"records {stray} do not belong to video {video_id!r}")


_WORD = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


class MemorySearchIndex:
    """Scores documents by the share of query terms they contain."""

    def __init__(self) -> None:
        self._docs: dict[str, SearchDoc] = {}

    def index(self, docs: Sequence[SearchDoc]) -> None:
        for doc in docs:
            self._docs[doc.id] = doc

    def remove_video(self, video_id: str) -> None:
        self._docs = {k: d for k, d in self._docs.items() if d.video_id != video_id}

    def search(self, query: SearchQuery) -> list[SearchHit]:
        wanted = _terms(query.text)
        if not wanted:
            return []
        hits = []
        for doc in self._docs.values():
            if doc.creator_id != query.creator_id or doc.kind not in query.kinds:
                continue
            score = len(wanted & _terms(doc.text)) / len(wanted)
            if score > 0:
                hits.append(
                    SearchHit(doc_id=doc.id, kind=doc.kind, video_id=doc.video_id, score=score)
                )
        hits.sort(key=lambda h: (-h.score, h.doc_id))
        return hits[: query.limit]


class MemoryEmbedder:
    """Deterministic bag-of-letters vectors. Only for exercising code paths in tests."""

    dimension = 26

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            counts = [0.0] * self.dimension
            for ch in text.lower():
                if "a" <= ch <= "z":
                    counts[ord(ch) - ord("a")] += 1
            vectors.append(counts)
        return vectors


Response = BaseModel | str | Callable[[str, str], Any]


class MemoryLLMClient:
    """A scripted LLM: tests queue the responses each task should return, in order.

    A queued response may be a value, or a callable taking (system, prompt) so a
    test can inspect what the pipeline sent.
    """

    def __init__(self, models: dict[str, str] | None = None) -> None:
        self._models = models or {}
        self._queues: dict[LLMTask, deque[Response]] = defaultdict(deque)
        self.calls: list[tuple[LLMTask, str, str]] = []

    def script(self, task: LLMTask, *responses: Response) -> None:
        self._queues[task].extend(responses)

    def model_for(self, task: LLMTask) -> str:
        return self._models.get(task.value, "memory")

    def generate_structured(
        self, task: LLMTask, system: str, prompt: str, output_type: type[T]
    ) -> T:
        result = self._next(task, system, prompt)
        if not isinstance(result, output_type):
            raise TypeError(
                f"scripted {task} response is {type(result).__name__}, "
                f"expected {output_type.__name__}"
            )
        return result

    def generate_text(self, task: LLMTask, system: str, prompt: str) -> str:
        result = self._next(task, system, prompt)
        if not isinstance(result, str):
            raise TypeError(f"scripted {task} response is {type(result).__name__}, expected str")
        return result

    def _next(self, task: LLMTask, system: str, prompt: str) -> Any:
        self.calls.append((task, system, prompt))
        if not self._queues[task]:
            raise LookupError(f"no scripted response left for task {task.value!r}")
        response = self._queues[task].popleft()
        return response(system, prompt) if callable(response) else response
