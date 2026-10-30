"""A creator's bio: who they are as a whole, from their own words (CreatorBio).

The model reads a compact catalogue of the creator's videos and the passages where
they talk about their work (their channel, brand, products, collaborations), and
writes a summary, a dated journey and their ventures, each item citing a quote.
Code keeps only items whose quotes are found in the cited video, and drops anything
about personal life (rule 8). Pure functions only: no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from askthe.core.answering import clean_description
from askthe.core.evaluation import personal_life
from askthe.core.models import BioCitation, BioItem, Creator, Segment, Video, VideoProfile
from askthe.core.profiling import normalise

# Phrases creators use when talking about their own work, whatever their niche.
WORK_PHRASES = (
    "my brand",
    "my company",
    "my store",
    "our store",
    "my business",
    "we make",
    "we made",
    "I designed",
    "my own",
    "my first video",
    "started this channel",
    "the channel name",
    "collaboration",
    "collab",
    "pre-order",
    "sample",
    "my team",
    "our studio",
)


class CitationDraft(BaseModel):
    video: str = Field(description="The video id, from the material.")
    quote: str = Field(description="A short quote copied exactly from that video.")


class ItemDraft(BaseModel):
    title: str
    text: str = Field(description="One or two sentences, third person.")
    when: str | None = Field(
        default=None, description="As precise as the material allows: '2019', 'Nov 2022'."
    )
    citations: list[CitationDraft]


class BioDraft(BaseModel):
    summary: str = Field(description="At most two sentences, about 40 words.")
    journey: list[ItemDraft] = Field(description="Milestones, oldest first.")
    ventures: list[ItemDraft] = Field(description="Their own brands, products, collaborations.")


def bio_system_prompt(creator: Creator) -> str:
    who = creator.refer_to_creator_as
    return f"""You write a short profile of {creator.display_name} ({creator.niche}) for \
the page fans see before asking questions: who {who} is as a whole, not one platform. \
Use only the material given: a catalogue of their videos (with descriptions) and \
passages where they talk about their own work.

Write:
- summary: at most two sentences, about 40 words, on who {who} is and what their work \
is about. It sits above the question box on a phone, so every word must earn its place.
- journey: 4 to 8 dated milestones in their work, oldest first: how the channel \
started and changed, formats, launching their own brand or products, collaborations, \
building a team or studio.
- ventures: their own brands, products and collaborations, each with what it is.

Rules:
- Third person, plain and respectful. Refer to them as "{who}" (or "{creator.pronoun}"), \
the way answers do, not by any other name. Facts are what they said, not verified truth.
- Every item cites one or two short quotes copied exactly from the material, with the \
video id. No quote, no item.
- Professional life only. Nothing about family, partners, friends, home, health, where \
they live or other private matters, even if the material mentions it.
- Sponsors and brands they review are not their ventures. Their own products are.
- Never guess: leave out what the material doesn't show. Fewer, well-supported items \
beat many thin ones.
- The catalogue is only some of their videos. Don't call anything their first, earliest \
or "the start" of something unless they say so in a quote; order by the dates shown, \
and when two things overlap in time, don't imply which came first."""


def bio_material(
    videos: Sequence[Video],
    profiles: Mapping[str, VideoProfile | None],
    passages: Sequence[tuple[Video, Segment]],
    description_words: int = 60,
) -> str:
    """The catalogue (oldest first) and the passages, labelled by video id."""
    lines = ["<catalogue>"]
    for v in sorted(videos, key=lambda v: v.published_at):
        profile = profiles.get(v.id)
        purpose = f" | {profile.purpose}" if profile else ""
        desc = " ".join(clean_description(v.description).split()[:description_words])
        lines.append(f"[{v.platform_id}] {v.published_at.date()} {v.title}{purpose}")
        if desc:
            lines.append(f"    description: {desc}")
    lines += ["</catalogue>", "<passages>"]
    for v, s in passages:
        lines.append(f"[{v.platform_id}] {v.published_at.date()} {v.title}\n{s.text}")
    lines.append("</passages>")
    return "\n".join(lines)


def check_bio(
    draft: BioDraft,
    texts: Mapping[str, str],
    pronoun: str,
) -> tuple[str, list[BioItem], list[BioItem], list[str]]:
    """Keep only citations whose quote appears in the cited video's text (transcript
    and description), and only items with at least one; drop anything mentioning
    personal life. Returns summary, journey, ventures and what was dropped."""
    dropped: list[str] = []

    def keep(items: Sequence[ItemDraft]) -> list[BioItem]:
        kept = []
        for item in items:
            if personal_life(f"{item.title} {item.text}", pronoun):
                dropped.append(f"{item.title}: mentions personal life")
                continue
            cites = [
                BioCitation(video_id=c.video, quote=c.quote)
                for c in item.citations
                if normalise(c.quote) and normalise(c.quote) in texts.get(c.video, "")
            ]
            if not cites:
                dropped.append(f"{item.title}: no quote could be verified")
                continue
            kept.append(BioItem(title=item.title, text=item.text, when=item.when, citations=cites))
        return kept

    summary = draft.summary
    if personal_life(summary, pronoun):
        dropped.append("summary: mentions personal life")
        summary = ""
    return summary, keep(draft.journey), keep(draft.ventures), dropped
