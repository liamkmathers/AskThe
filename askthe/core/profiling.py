"""Profiling: describing each video once, so the right videos can be found and read
well at question time.

A profile is metadata, not opinions: what the video is, its sections, what it covers,
where the sponsor reads and asides are, and the questions it answers. What the creator
thinks is left to question time, when the model reads his actual words with the
question in mind (docs/DECISIONS.md, D15).

Pure functions only: no I/O, no LLM calls.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from pydantic import BaseModel, Field

from askthe.core import ids
from askthe.core.models import (
    Correction,
    Creator,
    Entity,
    EntityType,
    OutlineSection,
    Passage,
    PassageRole,
    Resolution,
    Segment,
    Use,
    Video,
    VideoProfile,
    VideoType,
)

# Bump whenever the profile prompt, schema or conversion changes what is produced.
PROFILER_VERSION = "p1"


# --- What the LLM returns ---------------------------------------------------------


class Draft(BaseModel):
    pass


class EntityDraft(Draft):
    name: str = Field(description="Correct, canonical name. Use the glossary spelling.")
    type: EntityType
    brand: str | None = None
    category: str | None = Field(None, description="One of the creator's categories, if any.")
    heard_as: list[str] = Field(
        default_factory=list, description="Spellings in the transcript, including errors."
    )
    identified: bool = Field(
        description="False if the transcript doesn't make clear exactly what this is."
    )


class SectionDraft(Draft):
    title: str
    summary: str = Field(description="One or two sentences: what this section covers.")
    first_segment: int
    last_segment: int


class PassageDraft(Draft):
    role: PassageRole
    first_segment: int
    starts_with: str = Field(description="The first 4 to 8 words of the passage, exactly.")
    last_segment: int
    ends_with: str = Field(description="The last 4 to 8 words of the passage, exactly.")
    note: str = Field(description='e.g. "Sponsor read for a hair dryer".')


class CorrectionDraft(Draft):
    segment: int
    note: str = Field(description="What is corrected, and what the correction says.")


class ProfileDraft(Draft):
    purpose: str
    video_type: VideoType
    thesis: str
    key_takeaways: list[str]
    sections: list[SectionDraft]
    topics: list[str]
    entities: list[EntityDraft]
    categories: list[str]
    passages: list[PassageDraft] = Field(
        description="Intro, sponsor reads, asides (skits, jokes, personal life) and outro."
    )
    corrections: list[CorrectionDraft]
    answers_questions: list[str]
    uses: list[Use]
    related_videos: list[str]


# --- Prompts --------------------------------------------------------------------


def glossary_text(creator: Creator) -> str:
    return "\n".join(
        f"- {g.name} ({g.type.value})"
        + (f"; captions may write it as: {', '.join(g.heard_as)}" if g.heard_as else "")
        for g in creator.glossary
    )


def profile_system_prompt(creator: Creator) -> str:
    """Stable per creator, so it can be cached across every call."""
    return f"""You describe videos by one creator so that, later, the right videos can be \
found and read to answer fans' questions. You describe what each video is and how it is \
organised. You do not summarise or judge the creator's opinions; those are read from \
the transcript itself when a question is asked.

Creator: {creator.display_name} ({creator.niche}).
Their product categories: {", ".join(creator.categories)}.

Names: correct caption errors only when the transcript, title, description or glossary \
make the name clear. Otherwise keep the name as said and mark the entity as not \
identified. Never guess.

Glossary of known names:
{glossary_text(creator) or "(none yet)"}"""


def video_context(video: Video, segments: Sequence[Segment]) -> str:
    """One video with its numbered segments."""
    numbered = "\n\n".join(f"[{s.index}] {s.text}" for s in segments)
    chapters = "; ".join(video.chapters) if video.chapters else "(none)"
    return f"""<video>
Title: {video.title}
Published: {video.published_at.date().isoformat()}
Chapters: {chapters}
Description:
{video.description or "(none)"}

Transcript ({video.transcript_kind.value} captions), in numbered segments:
{numbered}
</video>"""


PROFILE_PROMPT = """Read the whole video above and describe it.

- purpose, video_type, thesis and key_takeaways describe the video as a whole.
- sections: the video's parts in order, each with a title, a one or two sentence \
summary of what it covers, and its segment range. Follow the creator's own structure \
(chapters, "number one...", "round two...") where there is one.
- entities: every product, component, material, brand, service, person and concept \
discussed, with correct names and the spellings the captions used.
- passages: the intro, every sponsor read, asides (skits, jokes, personal life) and \
the outro. Mark each by its exact first and last few words, which may be in the \
middle of a segment. Talk about the creator's own products or brand is not a sponsor \
read. Main content is not listed.
- corrections: where the video corrects something said earlier.
- answers_questions: 5 to 15 questions a fan might ask that this video answers well, \
in a fan's own words.
- related_videos: other videos it refers to, as titles or descriptions."""


# --- Turning the draft into records -------------------------------------------------


_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalise(text: str) -> str:
    """For comparing quotes and names: case, accents, punctuation and spacing ignored."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


class EntityResolver:
    """Maps names to entity IDs via the glossary and aliases already known."""

    def __init__(self, creator: Creator, known: Sequence[Entity] = ()) -> None:
        self._creator = creator
        self._canonical: dict[str, str] = {}
        for g in creator.glossary:
            for alias in [g.name, *g.heard_as]:
                self._canonical[normalise(alias)] = g.name
        self.entities: dict[str, Entity] = {}
        for e in known:
            self._remember(e)

    def _remember(self, entity: Entity) -> None:
        self.entities[entity.id] = entity
        for alias in [entity.canonical_name, *entity.aliases]:
            self._canonical.setdefault(normalise(alias), entity.canonical_name)

    def resolve(self, draft: EntityDraft) -> Entity:
        name = self._canonical.get(normalise(draft.name), draft.name)
        entity_id = ids.entity_id(self._creator.slug, name)
        existing = self.entities.get(entity_id)
        aliases = sorted({*(existing.aliases if existing else []), *draft.heard_as} - {name})
        resolution = Resolution.RESOLVED if draft.identified else Resolution.UNRESOLVED
        if existing and existing.resolution is Resolution.RESOLVED:
            resolution = Resolution.RESOLVED
        entity = Entity(
            id=entity_id,
            creator_id=self._creator.slug,
            type=existing.type if existing else draft.type,
            canonical_name=name,
            brand=(existing.brand if existing else None) or draft.brand,
            category=(existing.category if existing else None) or draft.category,
            aliases=aliases,
            resolution=resolution,
            related_entity_ids=existing.related_entity_ids if existing else [],
        )
        self._remember(entity)
        return entity


def segments_fingerprint(segments: Sequence[Segment]) -> str:
    """Identifies a segmentation: a profile's segment ranges hold only for this one."""
    digest = hashlib.sha256()
    for segment in sorted(segments, key=lambda s: s.index):
        digest.update(f"{segment.index}\x00{segment.text}\x1e".encode())
    return digest.hexdigest()[:16]


def profile_from_draft(
    video: Video,
    draft: ProfileDraft,
    entities: Sequence[Entity],
    segment_count: int,
    model: str,
) -> VideoProfile:
    last = max(segment_count - 1, 0)

    def clamp(i: int) -> int:
        return min(max(i, 0), last)

    return VideoProfile(
        video_id=video.id,
        purpose=draft.purpose,
        video_type=draft.video_type,
        thesis=draft.thesis,
        key_takeaways=draft.key_takeaways,
        outline=[
            OutlineSection(
                title=s.title,
                summary=s.summary,
                first_segment=clamp(s.first_segment),
                last_segment=clamp(max(s.first_segment, s.last_segment)),
            )
            for s in draft.sections
        ],
        passages=[
            Passage(
                role=p.role,
                first_segment=clamp(p.first_segment),
                starts_with=p.starts_with,
                last_segment=clamp(max(p.first_segment, p.last_segment)),
                ends_with=p.ends_with,
                note=p.note,
            )
            for p in draft.passages
        ],
        topics=draft.topics,
        entity_ids=list(dict.fromkeys(e.id for e in entities)),
        categories=draft.categories,
        answers_questions=draft.answers_questions,
        uses=draft.uses,
        corrections=[
            Correction(segment_id=ids.segment_id(video.id, clamp(c.segment)), note=c.note)
            for c in draft.corrections
        ],
        related_videos=draft.related_videos,
        profiler_version=PROFILER_VERSION,
        model=model,
    )


def profile_search_text(video: Video, profile: VideoProfile, entities: Sequence[Entity]) -> str:
    """What a video's profile contributes to search."""
    names = [n for e in entities for n in [e.canonical_name, *e.aliases]]
    sections = [f"{s.title}. {s.summary}" for s in profile.outline]
    return " ".join(
        [
            video.title,
            profile.purpose,
            profile.thesis,
            *profile.key_takeaways,
            *profile.topics,
            *names,
            *sections,
        ]
    )
