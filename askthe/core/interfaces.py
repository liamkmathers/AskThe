"""The ports: every external dependency the engine uses, as a small interface.

Implementations live in askthe/adapters/ and are chosen in askthe.toml. Only
askthe/wiring.py constructs them. See docs/ARCHITECTURE.md#swappable-components.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

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
    VideoMeta,
    VideoProfile,
)

T = TypeVar("T", bound=BaseModel)


# --- Fetching -------------------------------------------------------------------


@runtime_checkable
class CatalogSource(Protocol):
    """Lists a creator's videos and their metadata."""

    def list_videos(self, creator: Creator) -> list[VideoMeta]: ...

    def get_video(self, creator: Creator, platform_id: str) -> VideoMeta: ...


@runtime_checkable
class TranscriptSource(Protocol):
    """Gets a timestamped transcript for one video."""

    def get_transcript(self, platform_id: str) -> Transcript: ...


@runtime_checkable
class RawArchive(Protocol):
    """Stores fetched videos: the source of truth. Records are never modified."""

    def has(self, creator_slug: str, platform_id: str) -> bool: ...

    def save(self, raw: RawVideo) -> None: ...

    def load(self, creator_slug: str, platform_id: str) -> RawVideo: ...

    def list_ids(self, creator_slug: str) -> list[str]: ...


# --- Knowledge ------------------------------------------------------------------


@runtime_checkable
class KnowledgeStore(Protocol):
    """Saves and queries derived records. Everything here is rebuildable from raw."""

    def upsert_video(self, video: Video) -> None: ...

    def get_video(self, video_id: str) -> Video | None: ...

    def list_videos(self, creator_id: str) -> list[Video]: ...

    def replace_segments(self, video_id: str, segments: Sequence[Segment]) -> None: ...

    def get_segments(self, video_id: str) -> list[Segment]: ...

    def get_segment(self, segment_id: str) -> Segment | None: ...

    def save_profile(self, profile: VideoProfile) -> None: ...

    def get_profile(self, video_id: str) -> VideoProfile | None: ...

    def upsert_entity(self, entity: Entity) -> None: ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def list_entities(self, creator_id: str) -> list[Entity]: ...

    def upsert_version(self, version: ProductVersion) -> None: ...

    def list_versions(self, entity_id: str) -> list[ProductVersion]: ...

    def replace_claims(self, video_id: str, claims: Sequence[Claim]) -> None: ...

    def get_claims_for_video(self, video_id: str) -> list[Claim]: ...

    def get_claims_for_entity(self, entity_id: str) -> list[Claim]: ...

    def log_answer(self, log: AnswerLog) -> None: ...

    def list_answers(self, creator_id: str) -> list[AnswerLog]: ...


class DocKind(StrEnum):
    SEGMENT = "segment"
    CLAIM = "claim"
    PROFILE_QUESTION = "profile_question"


class SearchDoc(BaseModel):
    """Something findable: a segment, a claim, or a question a video answers."""

    id: str
    kind: DocKind
    creator_id: str
    video_id: str
    text: str


class SearchHit(BaseModel):
    doc_id: str
    kind: DocKind
    video_id: str
    score: float


class SearchQuery(BaseModel):
    text: str
    creator_id: str
    kinds: list[DocKind] = Field(default_factory=lambda: list(DocKind))
    limit: int = Field(default=20, ge=1)


@runtime_checkable
class SearchIndex(Protocol):
    """Finds relevant segments, claims and profile questions for a query."""

    def index(self, docs: Sequence[SearchDoc]) -> None: ...

    def remove_video(self, video_id: str) -> None: ...

    def search(self, query: SearchQuery) -> list[SearchHit]: ...


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors. Not used until vector search is added."""

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


# --- LLM ------------------------------------------------------------------------


class LLMTask(StrEnum):
    """What the model is being asked to do. Config maps each task to a model."""

    UNDERSTAND = "understand"
    EXTRACT = "extract"
    ANSWER = "answer"


@runtime_checkable
class LLMClient(Protocol):
    """Structured and free-text generation. Model choice is the adapter's, from config."""

    def generate_structured(
        self, task: LLMTask, system: str, prompt: str, output_type: type[T]
    ) -> T: ...

    def generate_text(self, task: LLMTask, system: str, prompt: str) -> str: ...

    def model_for(self, task: LLMTask) -> str: ...
