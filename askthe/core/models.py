"""Domain models: the records described in docs/DATA_MODEL.md.

These are plain data objects. They know nothing about YouTube, databases or LLM
APIs; adapters translate to and from them at the boundary.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# --- Enumerations ---------------------------------------------------------------


class TranscriptKind(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class VideoType(StrEnum):
    REVIEW = "review"
    COMPARISON = "comparison"
    RANKING = "ranking"
    LONG_TERM_REVIEW = "long_term_review"
    EXPLAINER = "explainer"
    HOW_TO = "how_to"
    OTHER = "other"


class PassageRole(StrEnum):
    """Stretches of a video that aren't its main content."""

    INTRO = "intro"
    SPONSOR = "sponsor"
    ASIDE = "aside"  # skits, jokes, tangents, personal life
    OUTRO = "outro"


class Use(StrEnum):
    BUYING_DECISION = "buying_decision"
    CARE_MAINTENANCE = "care_maintenance"
    UNDERSTANDING = "understanding"
    BACKGROUND_HISTORY = "background_history"
    STYLE = "style"


class EntityType(StrEnum):
    PRODUCT = "product"
    COMPONENT = "component"
    MATERIAL = "material"
    BRAND = "brand"
    SERVICE = "service"
    PERSON = "person"
    CONCEPT = "concept"


class Resolution(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class ClaimKind(StrEnum):
    VERDICT = "verdict"
    PREFERENCE = "preference"
    COMPARISON = "comparison"
    RANKING = "ranking"
    DURABILITY = "durability"
    FIT_SIZING = "fit_sizing"
    EXPLANATION = "explanation"
    HISTORY = "history"
    ADVICE = "advice"
    TECHNIQUE = "technique"
    BRAND_OPINION = "brand_opinion"
    BUYING_PRINCIPLE = "buying_principle"
    MENTION = "mention"
    SPONSORSHIP = "sponsorship"
    OTHER = "other"


class HeldByKind(StrEnum):
    CREATOR = "creator"
    OTHERS = "others"
    BRAND = "brand"
    PERSON = "person"


class Aspect(StrEnum):
    OVERALL = "overall"
    VALUE = "value"
    QUALITY = "quality"
    DURABILITY = "durability"
    FIT = "fit"
    COMFORT = "comfort"
    WARMTH = "warmth"
    LOOKS = "looks"
    ETHICS = "ethics"
    PERFORMANCE = "performance"


class Stance(StrEnum):
    RECOMMEND = "recommend"
    POSITIVE = "positive"
    MIXED = "mixed"
    NEGATIVE = "negative"
    AVOID = "avoid"
    NEUTRAL = "neutral"


class Certainty(StrEnum):
    FIRM = "firm"
    TENTATIVE = "tentative"
    SPECULATIVE = "speculative"


class Basis(StrEnum):
    # Records why the creator holds a view, never how much it counts.
    PERSONAL_TASTE = "personal_taste"
    OWN_TESTING = "own_testing"
    LONG_TERM_WEAR = "long_term_wear"
    RESEARCH = "research"
    INTERVIEW = "interview"
    HEARSAY = "hearsay"


class PriceType(StrEnum):
    RETAIL = "retail"
    SALE = "sale"
    USED = "used"
    UNSPECIFIED = "unspecified"


class BuyCondition(StrEnum):
    NEW = "new"
    USED = "used"
    VINTAGE = "vintage"
    ON_SALE = "on_sale"


class Coverage(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


# --- Creator config -------------------------------------------------------------


class GlossaryEntry(Model):
    name: str
    type: EntityType
    heard_as: list[str] = Field(default_factory=list)


class ChannelInfo(Model):
    """The creator's channel as the platform describes it, fetched by `askthe channel`
    into data/<slug>/channel.json. Refreshed by fetching again, so not raw data."""

    title: str = ""
    description: str = ""
    avatar_url: str | None = None
    banner_url: str | None = None
    subscribers: int | None = None
    video_count: int | None = None
    fetched_at: datetime | None = None


class Creator(Model):
    """A creator instance ("Ask The <creator>"), loaded from creators/<slug>.yaml."""

    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    display_name: str
    instance_name: str
    platform: str
    channel_url: str
    niche: str
    refer_to_creator_as: str
    pronoun: str
    categories: list[str]
    video_selection: str | None = None
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    starter_questions: list[str] = Field(default_factory=list)  # shown on the ask page
    # Shown on the creator's page and catalog card. `about` and `tagline` are written
    # in the creator config; the channel fields come from `askthe channel`
    # (data/<slug>/channel.json) and are filled in when the creator is loaded.
    tagline: str | None = None  # one line for the catalog card
    about: str | None = None  # a short paragraph about the channel, never personal life
    channel: ChannelInfo | None = None

    @property
    def id(self) -> str:
        return self.slug


# --- Raw layer ------------------------------------------------------------------


class VideoListing(Model):
    """A video as it appears in a channel listing: enough to choose which to fetch."""

    platform_id: str
    title: str = ""
    duration_s: float | None = None


class VideoMeta(Model):
    """Metadata as fetched from the platform."""

    platform_id: str
    title: str
    description: str = ""
    published_at: datetime
    duration_s: float = Field(ge=0)
    chapters: list[str] = Field(default_factory=list)  # chapter titles, in order
    tags: list[str] = Field(default_factory=list)
    view_count: int | None = None
    thumbnail_url: str | None = None


class Transcript(Model):
    """The spoken text of a video. No timing: nothing in the system depends on it."""

    kind: TranscriptKind
    language: str
    text: str = Field(min_length=1)


class RawVideo(Model):
    """One fetched video: the source of truth everything else is rebuilt from."""

    creator_slug: str
    meta: VideoMeta
    transcript: Transcript
    fetched_at: datetime
    source: str  # which adapter fetched it, e.g. "yt-dlp"


class Comment(Model):
    """A viewer's comment on a video. Authors are not stored: only what was asked."""

    id: str  # the platform's comment ID, so the comment can be linked to
    text: str
    like_count: int = 0
    is_reply: bool = False
    by_creator: bool = False
    published_at: datetime | None = None


class RawComments(Model):
    """Comments fetched for one video. Raw data: saved once, never modified."""

    creator_slug: str
    platform_id: str
    comments: list[Comment]
    fetched_at: datetime
    source: str


# --- Segment layer --------------------------------------------------------------


class Video(Model):
    id: str
    creator_id: str
    platform_id: str
    title: str
    description: str = ""
    published_at: datetime
    duration_s: float = Field(ge=0)
    chapters: list[str] = Field(default_factory=list)  # chapter titles, in order
    tags: list[str] = Field(default_factory=list)
    view_count: int | None = None
    thumbnail_url: str | None = None
    transcript_kind: TranscriptKind


class Segment(Model):
    """A chunk of transcript, in order. Claims cite segments; quotes must appear in them."""

    id: str
    video_id: str
    index: int = Field(ge=0)  # position in the video
    text: str = Field(min_length=1)


# --- Knowledge layer ------------------------------------------------------------


class OutlineSection(Model):
    title: str
    summary: str = ""
    first_segment: int = Field(ge=0)
    last_segment: int = Field(ge=0)


class Passage(Model):
    """A non-main stretch (such as a sponsor read), pinned to its exact first and last
    words so it can be marked precisely inside the transcript, even mid-segment."""

    role: PassageRole
    first_segment: int = Field(ge=0)
    starts_with: str
    last_segment: int = Field(ge=0)
    ends_with: str
    note: str = ""


class Correction(Model):
    segment_id: str
    note: str


class VideoProfile(Model):
    video_id: str
    purpose: str
    video_type: VideoType
    thesis: str
    key_takeaways: list[str] = Field(default_factory=list)
    outline: list[OutlineSection] = Field(default_factory=list)
    passages: list[Passage] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    answers_questions: list[str] = Field(default_factory=list)
    uses: list[Use] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    related_videos: list[str] = Field(default_factory=list)
    profiler_version: str
    model: str


class Entity(Model):
    id: str
    creator_id: str
    type: EntityType
    canonical_name: str
    brand: str | None = None
    model: str | None = None
    category: str | None = None
    aliases: list[str] = Field(default_factory=list)
    resolution: Resolution = Resolution.RESOLVED
    related_entity_ids: list[str] = Field(default_factory=list)
    affiliate_url: str | None = None


class ProfileRecord(Model):
    """A profile saved outside the database, with the entities it names (D17).

    `segments_fingerprint` identifies the segmentation the profile's segment ranges
    refer to; a record whose fingerprint no longer matches is stale and not restored.
    """

    platform_id: str
    profile: VideoProfile
    entities: list[Entity] = Field(default_factory=list)
    segments_fingerprint: str


class ProductVersion(Model):
    id: str
    entity_id: str
    label: str
    era: str | None = None
    made_in: str | None = None
    materials: list[str] = Field(default_factory=list)
    notes: str | None = None


class HeldBy(Model):
    kind: HeldByKind = HeldByKind.CREATOR
    name: str | None = None  # for a named person or brand


class Price(Model):
    amount: float | None = Field(default=None, ge=0)
    amount_max: float | None = Field(default=None, ge=0)
    currency: str | None = None
    type: PriceType = PriceType.UNSPECIFIED
    as_said: str


class BuyAdvice(Model):
    condition: BuyCondition | None = None
    notes: str | None = None


class Ranking(Model):
    list_name: str
    criterion: Aspect
    position: int | None = Field(default=None, ge=1)
    category: str | None = None


class ComparedWith(Model):
    entity_ids: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)
    aspect: Aspect = Aspect.OVERALL
    winner_id: str | None = None


class Claim(Model):
    """One thing said in a video, tied to where it was said."""

    id: str
    video_id: str
    segment_ids: list[str] = Field(min_length=1)
    quote: str = Field(min_length=1)
    kind: ClaimKind
    entity_ids: list[str] = Field(default_factory=list)
    version_ids: list[str] = Field(default_factory=list)
    statement: str
    held_by: HeldBy = Field(default_factory=HeldBy)
    aspect: Aspect | None = None
    stance: Stance | None = None
    certainty: Certainty = Certainty.FIRM
    basis: Basis | None = None
    he_wears_it: bool = False
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    good_for: list[str] = Field(default_factory=list)
    bad_for: list[str] = Field(default_factory=list)
    price: Price | None = None
    buy_advice: BuyAdvice | None = None
    fit_advice: str | None = None
    ranking: Ranking | None = None
    compared_with: ComparedWith | None = None
    context: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    use: Use | None = None
    sponsored: bool = False
    superseded_by: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    extractor_version: str
    model: str

    @model_validator(mode="after")
    def _consistent(self) -> Claim:
        if self.kind is ClaimKind.SPONSORSHIP and not self.sponsored:
            raise ValueError("sponsorship claims must be marked sponsored")
        return self

    @property
    def is_creators_view(self) -> bool:
        return self.held_by.kind is HeldByKind.CREATOR


class AnswerSource(Model):
    """One verified citation in an answer: the quote and where it came from."""

    n: int  # the [n] marker in the answer text
    video_id: str
    title: str
    published: date
    url: str
    segment_ids: list[str] = Field(default_factory=list)  # empty for a description quote
    quote: str
    # His words around the quote, verbatim, so a reader can see what it was part of.
    context_before: str = ""
    context_after: str = ""
    in_description: bool = False  # quoted from the video's description
    sponsored: bool = False  # inside a sponsor read, as marked in code (rule 6)


class AnswerLog(Model):
    """A question and the answer given: a snapshot fans can come back to (UI_PLAN)."""

    id: str
    creator_id: str
    asked_at: datetime
    question: str
    answer: str
    covered: Coverage
    changed_mind: bool = False
    sources: list[AnswerSource] = Field(default_factory=list)
    videos_read: list[str] = Field(default_factory=list)  # video IDs the answer was based on
    parent_id: str | None = None  # the answer this follows up, for a later chat thread
    flagged: list[str] = Field(default_factory=list)  # "something wrong?" notes from fans
    cited_claim_ids: list[str] = Field(default_factory=list)
    cited_segment_ids: list[str] = Field(default_factory=list)
    pipeline_versions: dict[str, str] = Field(default_factory=dict)
