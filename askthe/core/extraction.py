"""Extraction: what the LLM is asked for, and how its answers become checked records.

Two passes (docs/ARCHITECTURE.md, stage 3). Pass A reads the whole video and writes a
profile; pass B extracts claims from a window of segments, with the whole video and
its profile as context. The LLM's output uses simple "draft" shapes that refer to
segments by number and entities by name; this module turns drafts into domain records
and enforces the rules the model can't be trusted to keep: quotes must really be in
the cited segment, sponsor segments are always sponsored, names go through the
glossary, and nothing is invented to fill a gap.

Pure functions only: no I/O, no LLM calls.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from askthe.core import ids
from askthe.core.models import (
    Aspect,
    Basis,
    BuyAdvice,
    BuyCondition,
    Certainty,
    Claim,
    ClaimKind,
    ComparedWith,
    Correction,
    Creator,
    Entity,
    EntityType,
    HeldBy,
    HeldByKind,
    OutlineSection,
    Price,
    PriceType,
    ProductVersion,
    Ranking,
    Resolution,
    Segment,
    SegmentRole,
    Stance,
    Use,
    Video,
    VideoProfile,
    VideoType,
)

# Bump whenever prompts, draft schemas or conversion rules change what is extracted.
EXTRACTOR_VERSION = "x3"


# --- Draft shapes: what the LLM returns -----------------------------------------


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


class SegmentRangeRole(Draft):
    first_segment: int
    last_segment: int
    role: SegmentRole


class OutlineDraft(Draft):
    title: str
    first_segment: int
    last_segment: int


class CorrectionDraft(Draft):
    segment: int
    note: str = Field(description="What is corrected, and what the correction says.")


class ProfileDraft(Draft):
    purpose: str
    video_type: VideoType
    thesis: str
    key_takeaways: list[str]
    outline: list[OutlineDraft]
    topics: list[str]
    entities: list[EntityDraft]
    categories: list[str]
    non_main_segments: list[SegmentRangeRole] = Field(
        description="Ranges that are intro, sponsor, aside or outro. Unlisted = main."
    )
    corrections: list[CorrectionDraft]
    answers_questions: list[str]
    uses: list[Use]
    related_videos: list[str]


class AttributeDraft(Draft):
    key: str
    value: str


def _choices(enum: type) -> str:
    return ", ".join(f'"{m.value}"' for m in enum)


# Claim drafts are deliberately flat: every field is always present, with "" or [] or
# 0 meaning "not said". Optional and nested fields multiply the size of the grammar
# the API compiles for structured output, past its limit. Code turns these strings
# into typed values in claims_from_drafts, with safe fallbacks.
class ClaimDraft(Draft):
    segment: int = Field(description="Number of the segment the quote is in.")
    quote: str = Field(description="Exact words copied from that segment. Never paraphrased.")
    kind: str = Field(description=f"One of: {_choices(ClaimKind)}.")
    entities: list[str] = Field(description="Names of the entities the claim is about.")
    statement: str = Field(description='One sentence, third person: "He says ..."')
    held_by: str = Field(description=f"One of: {_choices(HeldByKind)}.")
    held_by_name: str = Field(description='Named person or brand holding the view, or "".')
    aspect: str = Field(description=f'One of: {_choices(Aspect)}; or "" if not a judgement.')
    stance: str = Field(description=f'One of: {_choices(Stance)}; or "" if not a judgement.')
    certainty: str = Field(description=f"One of: {_choices(Certainty)}.")
    basis: str = Field(description=f'One of: {_choices(Basis)}; or "".')
    he_wears_it: bool
    pros: list[str]
    cons: list[str]
    good_for: list[str]
    bad_for: list[str]
    price_as_said: str = Field(description='Price in his words, or "".')
    price_amount: float = Field(description="Price as a number, or 0.")
    price_amount_max: float = Field(description="Upper end of a price range, or 0.")
    price_currency: str = Field(description='e.g. "USD", or "".')
    price_type: str = Field(description=f'One of: {_choices(PriceType)}; or "".')
    buy_condition: str = Field(description=f'One of: {_choices(BuyCondition)}; or "".')
    buy_notes: str = Field(description='Where or how to buy, in brief, or "".')
    fit_advice: str = Field(description='Sizing advice, or "".')
    version_label: str = Field(
        description='The specific version of the first entity, e.g. "Vintage, made in USA"; or "".'
    )
    version_era: str
    version_made_in: str
    ranking_list: str = Field(description='Name of the ranked list, or "".')
    ranking_criterion: str = Field(description=f'One of: {_choices(Aspect)}; or "".')
    ranking_position: int = Field(description="1 for first place; 0 if not ranked.")
    compared_against: list[str] = Field(description="Names of other entities compared.")
    comparison_aspect: str = Field(description=f'One of: {_choices(Aspect)}; or "".')
    comparison_winner: str = Field(description='Name of the winner, or "".')
    context: str = Field(description='Conditions the claim depends on, or "".')
    attributes: list[AttributeDraft]
    use: str = Field(description=f'One of: {_choices(Use)}; or "".')
    confidence: float = Field(description="0 to 1: how sure you are of this reading.")


class ClaimsDraft(Draft):
    claims: list[ClaimDraft]


# --- Prompts --------------------------------------------------------------------


def system_prompt(creator: Creator) -> str:
    """Stable per creator, so it can be cached across every call."""
    glossary = "\n".join(
        f"- {g.name} ({g.type.value})"
        + (f"; captions may write it as: {', '.join(g.heard_as)}" if g.heard_as else "")
        for g in creator.glossary
    )
    who = creator.refer_to_creator_as
    return f"""You are building a knowledge base of what one creator says in their videos, \
so fans can later ask questions and get the creator's own answer, quoted and linked.

Creator: {creator.display_name} ({creator.niche}). Refer to them as "{who}" or "{creator.pronoun}".
Their product categories: {", ".join(creator.categories)}.

Rules. These matter more than completeness on any one field.
1. His opinion is the product. Facts can be found elsewhere; his taste and judgement \
can't. Capture every opinion and preference, however brief or offhand ("I like these \
just because they're brown", "I wear it all the time"). Personal taste is never weaker \
evidence; record it as basis "personal_taste".
2. Quotes are verbatim. Copy the exact words from the numbered segment you cite. Never \
paraphrase, merge or tidy a quote. Keep quotes short: the words that carry the claim.
3. Attribute. Statements are third person ("He says..."). Facts and history are what he \
says, not verified truth. If he reports what others think ("people say it pills"), \
held_by is "others" (or "brand" for a company's own claim), never "creator".
4. Keep his hedging. "I guess", "probably", "I'm not sure" mean certainty "tentative" \
or "speculative". Never strengthen a claim.
5. Sponsored is never a verdict. Anything in a sponsor read, even "we've been using it \
and it's great", is kind "sponsorship". His own products or brand are not sponsorship: \
what he says about them is his opinion, extracted like any other claim, with the \
attribute own_product = "yes".
6. No personal life. Nothing about the personal life of the creator, family or friends \
(relationships, health, home life). Skits and jokes produce nothing unless they contain \
a real claim about the subject matter.
7. Never guess a name. Correct caption errors only when the transcript, title, \
description or glossary make the name clear. Otherwise keep the name as said and mark \
the entity as not identified.
8. Judge one aspect at a time. "Great quality but odd fit" is two claims (quality \
positive, fit negative). Use aspect "overall" only for a whole verdict.
9. Versions. If he contrasts versions of a product (vintage vs modern, made in USA vs \
not), attach the version to the claim.
10. Corrections. If the video later corrects itself, extract both; the profile records \
the correction.

Glossary of known names:
{glossary or "(none yet)"}"""


def video_context(video: Video, segments: Sequence[Segment]) -> str:
    """The whole video, numbered. Shared by every call for this video, so it's cached."""
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


UNDERSTAND_PROMPT = """Read the whole video above and write its profile.

- purpose, video_type, thesis and key_takeaways describe the video as a whole.
- outline: the video's sections as segment ranges, in order.
- entities: every product, component, material, brand, service, person and concept \
discussed, with correct names (see rule 7) and the spellings the captions used.
- non_main_segments: the intro, sponsor reads, asides (skits, jokes, personal life) and \
outro, as segment ranges. Everything not listed is main content.
- corrections: where the video corrects something said earlier.
- answers_questions: 5 to 15 questions a fan might ask that this video answers well, \
in a fan's own words.
- related_videos: other videos it refers to, as titles or descriptions."""


def profile_summary(profile: VideoProfile, entities: Sequence[Entity]) -> str:
    names = ", ".join(e.canonical_name for e in entities) or "(none)"
    return f"""<profile>
Purpose: {profile.purpose}
Type: {profile.video_type.value}
Thesis: {profile.thesis}
Entities: {names}
</profile>"""


def extract_prompt(
    profile_text: str, window: Sequence[Segment], roles: dict[int, SegmentRole]
) -> str:
    first, last = window[0].index, window[-1].index
    marked = [f"{s.index} ({roles.get(s.index, SegmentRole.MAIN).value})" for s in window]
    return f"""{profile_text}

Extract every claim made in segments {first} to {last} only: {", ".join(marked)}.
Use the rest of the video for context, but cite only these segments. Use entity names \
from the profile where they match. Return an empty list if these segments contain no \
claims (for example, a skit)."""


# --- Turning drafts into records --------------------------------------------------


_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalise(text: str) -> str:
    """For comparing quotes and names: case, accents, punctuation and spacing ignored."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def quote_location(quote: str, segment_index: int, segments: Sequence[Segment]) -> list[int]:
    """Segments the quote appears in, starting at the cited one; [] if it isn't there.

    A quote may run on into the next segment, so the cited segment joined with its
    successor is also checked.
    """
    wanted = normalise(quote)
    by_index = {s.index: s for s in segments}
    cited = by_index.get(segment_index)
    if not wanted or cited is None:
        return []
    if wanted in normalise(cited.text):
        return [segment_index]
    following = by_index.get(segment_index + 1)
    if following and wanted in normalise(f"{cited.text} {following.text}"):
        return [segment_index, segment_index + 1]
    return []


class EntityResolver:
    """Maps names used in drafts to entity IDs, via the glossary and known aliases."""

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

    def id_for(self, name: str) -> str:
        """ID for a name seen in a claim; unknown names become unresolved entities."""
        canonical = self._canonical.get(normalise(name), name)
        entity_id = ids.entity_id(self._creator.slug, canonical)
        if entity_id not in self.entities:
            self.resolve(EntityDraft(name=canonical, type=EntityType.PRODUCT, identified=False))
        return entity_id


def profile_from_draft(
    video: Video,
    draft: ProfileDraft,
    entities: Sequence[Entity],
    segment_count: int,
    model: str,
) -> tuple[VideoProfile, dict[int, SegmentRole]]:
    """The profile record, plus the role of every segment (main unless listed)."""
    last = max(segment_count - 1, 0)

    def clamp(i: int) -> int:
        return min(max(i, 0), last)

    roles = {i: SegmentRole.MAIN for i in range(segment_count)}
    for r in draft.non_main_segments:
        for i in range(clamp(r.first_segment), clamp(r.last_segment) + 1):
            roles[i] = r.role
    profile = VideoProfile(
        video_id=video.id,
        purpose=draft.purpose,
        video_type=draft.video_type,
        thesis=draft.thesis,
        key_takeaways=draft.key_takeaways,
        outline=[
            OutlineSection(
                title=o.title,
                first_segment=clamp(o.first_segment),
                last_segment=clamp(max(o.first_segment, o.last_segment)),
            )
            for o in draft.outline
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
        extractor_version=EXTRACTOR_VERSION,
        model=model,
    )
    return profile, roles


@dataclass
class ClaimBuild:
    claims: list[Claim] = field(default_factory=list)
    versions: list[ProductVersion] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)  # why drafts were dropped


def _enum[E](enum: type[E], value: str, default: E | None = None) -> E | None:
    try:
        return enum(value.strip().lower()) if value.strip() else default
    except ValueError:
        return default


def claims_from_drafts(
    video: Video,
    drafts: Sequence[ClaimDraft],
    segments: Sequence[Segment],
    roles: dict[int, SegmentRole],
    resolver: EntityResolver,
    model: str,
    first_index: int = 0,
) -> ClaimBuild:
    """Checked claims from drafts. Drafts whose quote isn't in the cited segment are
    dropped and reported, never repaired. Unrecognised enum values fall back safely:
    to "other" for the kind, to "others"/"tentative" for attribution and certainty
    (never to the creator's firm view), and to unset for everything else."""
    build = ClaimBuild()
    for draft in drafts:
        located = quote_location(draft.quote, draft.segment, segments)
        if not located:
            build.rejected.append(
                f"quote not found in segment {draft.segment}: {draft.quote[:80]!r}"
            )
            continue
        entity_ids = list(dict.fromkeys(resolver.id_for(n) for n in draft.entities if n.strip()))
        version_ids: list[str] = []
        if draft.version_label.strip() and entity_ids:
            version = ProductVersion(
                id=ids.version_id(entity_ids[0], draft.version_label),
                entity_id=entity_ids[0],
                label=draft.version_label,
                era=draft.version_era or None,
                made_in=draft.version_made_in or None,
            )
            build.versions.append(version)
            version_ids.append(version.id)

        kind = _enum(ClaimKind, draft.kind, ClaimKind.OTHER)
        sponsored = kind is ClaimKind.SPONSORSHIP or any(
            roles.get(i) is SegmentRole.SPONSOR for i in located
        )
        # An unreadable attribution or certainty must never default to the creator's
        # firm view: that would strengthen or misattribute the claim.
        held_by = _enum(HeldByKind, draft.held_by, HeldByKind.OTHERS)
        certainty = _enum(Certainty, draft.certainty, Certainty.TENTATIVE)

        price = None
        if draft.price_as_said.strip():
            price = Price(
                amount=draft.price_amount or None,
                amount_max=draft.price_amount_max or None,
                currency=draft.price_currency or None,
                type=_enum(PriceType, draft.price_type, PriceType.UNSPECIFIED),
                as_said=draft.price_as_said,
            )
        ranking = None
        criterion = _enum(Aspect, draft.ranking_criterion)
        if draft.ranking_list.strip() and criterion:
            ranking = Ranking(
                list_name=draft.ranking_list,
                criterion=criterion,
                position=draft.ranking_position or None,
            )
        compared = None
        if draft.compared_against:
            compared = ComparedWith(
                entity_ids=[resolver.id_for(n) for n in draft.compared_against if n.strip()],
                aspect=_enum(Aspect, draft.comparison_aspect, Aspect.OVERALL),
                winner_id=resolver.id_for(draft.comparison_winner)
                if draft.comparison_winner.strip()
                else None,
            )
        condition = _enum(BuyCondition, draft.buy_condition)
        build.claims.append(
            Claim(
                id=ids.claim_id(video.id, first_index + len(build.claims)),
                video_id=video.id,
                segment_ids=[ids.segment_id(video.id, i) for i in located],
                quote=draft.quote,
                kind=ClaimKind.SPONSORSHIP if sponsored else kind,
                entity_ids=entity_ids,
                version_ids=version_ids,
                statement=draft.statement,
                held_by=HeldBy(kind=held_by, name=draft.held_by_name or None),
                aspect=_enum(Aspect, draft.aspect),
                stance=_enum(Stance, draft.stance),
                certainty=certainty,
                basis=_enum(Basis, draft.basis),
                he_wears_it=draft.he_wears_it,
                pros=draft.pros,
                cons=draft.cons,
                good_for=draft.good_for,
                bad_for=draft.bad_for,
                price=price,
                buy_advice=BuyAdvice(condition=condition, notes=draft.buy_notes or None)
                if condition or draft.buy_notes.strip()
                else None,
                fit_advice=draft.fit_advice or None,
                ranking=ranking,
                compared_with=compared,
                context=draft.context or None,
                attributes={a.key: a.value for a in draft.attributes},
                use=_enum(Use, draft.use),
                sponsored=sponsored,
                confidence=min(max(draft.confidence, 0.0), 1.0),
                extractor_version=EXTRACTOR_VERSION,
                model=model,
            )
        )
    return build


def windows(segments: Sequence[Segment], size: int) -> list[list[Segment]]:
    ordered = sorted(segments, key=lambda s: s.index)
    return [ordered[i : i + size] for i in range(0, len(ordered), size)]
