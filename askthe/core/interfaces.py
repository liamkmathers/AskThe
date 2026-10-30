"""The ports: every external dependency the engine uses, as a small interface.

Implementations live in askthe/adapters/ and are chosen in askthe.toml. Only
askthe/wiring.py constructs them. See docs/ARCHITECTURE.md#swappable-components.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

from askthe.core.models import (
    AnswerLog,
    ChannelInfo,
    Claim,
    Comment,
    Creator,
    Entity,
    ProductVersion,
    ProfileRecord,
    RawComments,
    RawVideo,
    Segment,
    Transcript,
    Video,
    VideoListing,
    VideoMeta,
    VideoProfile,
)

T = TypeVar("T", bound=BaseModel)


# --- Fetching -------------------------------------------------------------------


@runtime_checkable
class CatalogSource(Protocol):
    """Lists a creator's videos and fetches their metadata."""

    def list_videos(self, creator: Creator) -> list[VideoListing]: ...

    def get_video(self, creator: Creator, platform_id: str) -> VideoMeta: ...

    def get_channel(self, creator: Creator) -> ChannelInfo:
        """The channel as the platform describes it: name, description, avatar."""
        ...


@runtime_checkable
class TranscriptSource(Protocol):
    """Gets a timestamped transcript for one video."""

    def get_transcript(self, platform_id: str) -> Transcript: ...


@runtime_checkable
class CommentSource(Protocol):
    """Gets viewers' comments on one video, most liked first where the platform can."""

    def get_comments(self, platform_id: str, limit: int) -> list[Comment]: ...


@runtime_checkable
class RawArchive(Protocol):
    """Stores fetched videos and their comments: the source of truth. Never modified."""

    def has(self, creator_slug: str, platform_id: str) -> bool: ...

    def save(self, raw: RawVideo) -> None: ...

    def load(self, creator_slug: str, platform_id: str) -> RawVideo: ...

    def list_ids(self, creator_slug: str) -> list[str]: ...

    def has_comments(self, creator_slug: str, platform_id: str) -> bool: ...

    def save_comments(self, raw: RawComments) -> None: ...

    def load_comments(self, creator_slug: str, platform_id: str) -> RawComments: ...

    def list_comment_ids(self, creator_slug: str) -> list[str]: ...


@runtime_checkable
class ProfileArchive(Protocol):
    """Keeps video profiles outside the database, since they cost an LLM call to make.

    Derived, so a record may be replaced; the database is rebuilt from these (D17).
    """

    def save(self, creator_slug: str, record: ProfileRecord) -> None: ...

    def load(self, creator_slug: str, platform_id: str) -> ProfileRecord | None: ...

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

    def log_answer(self, log: AnswerLog) -> None:
        """Save an answer, replacing any saved before with the same ID."""
        ...

    def get_answer(self, answer_id: str) -> AnswerLog | None: ...

    def list_answers(self, creator_id: str) -> list[AnswerLog]: ...


class DocKind(StrEnum):
    SEGMENT = "segment"
    PROFILE = "profile"  # a video's purpose, thesis, sections, topics and names
    PROFILE_QUESTION = "profile_question"


class SearchDoc(BaseModel):
    """Something findable: a segment, a video profile, or a question a video answers."""

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
    """Keyword search over segments, profiles and profile questions."""

    def index(self, docs: Sequence[SearchDoc]) -> None: ...

    def remove_video(self, video_id: str) -> None: ...

    def search(self, query: SearchQuery) -> list[SearchHit]: ...


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors that are close when meanings are close."""

    @property
    def name(self) -> str:
        """Identifies the model: vectors from different embedders are never mixed."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorItem(BaseModel):
    id: str  # same ID as the matching SearchDoc
    kind: DocKind
    creator_id: str
    video_id: str
    content_hash: str  # of the embedded text and embedder name; unchanged means skip
    vector: list[float]


class VectorHit(BaseModel):
    doc_id: str
    kind: DocKind
    video_id: str
    score: float  # cosine similarity: higher is closer


@runtime_checkable
class VectorIndex(Protocol):
    """Nearest-neighbour search over embedded documents."""

    def upsert(self, items: Sequence[VectorItem]) -> None: ...

    def content_hashes(self, video_id: str) -> dict[str, str]: ...

    def remove_video(self, video_id: str) -> None: ...

    def remove(self, ids: Sequence[str]) -> None: ...

    def search(
        self, vector: Sequence[float], creator_id: str, kinds: Sequence[DocKind], limit: int
    ) -> list[VectorHit]: ...


# --- LLM ------------------------------------------------------------------------


class LLMTask(StrEnum):
    """What the model is being asked to do. Config maps each task to a model."""

    UNDERSTAND = "understand"  # profile a video
    PLAN = "plan"  # turn a question into search queries
    RERANK = "rerank"  # score retrieved passages for relevance
    ANSWER = "answer"


class EmbeddingError(Exception):
    """Text could not be embedded (no key, rejected, unreachable)."""


class LLMError(Exception):
    """The model could not produce a usable answer (refused, truncated, unparseable)."""


@dataclass(frozen=True)
class Generated[M]:
    value: M
    model: str  # the model that actually answered, which may be a fallback
    usage: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """Structured generation. Model choice is the adapter's, from config.

    `context` is a large input shared by several calls (such as a whole transcript);
    adapters may cache it. It comes before `prompt`, which varies per call.

    With `on_text`, the response is streamed: `on_text` receives each piece of the raw
    structured (JSON) output as it's generated, for showing progress. The returned
    value is the same either way.
    """

    def generate_structured(
        self,
        task: LLMTask,
        system: str,
        prompt: str,
        output_type: type[T],
        context: str | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> Generated[T]: ...

    def model_for(self, task: LLMTask) -> str: ...
