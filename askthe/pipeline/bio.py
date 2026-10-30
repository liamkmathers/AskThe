"""Make a creator's bio (core/bio.py) and save it to data/<slug>/bio.json.

One model call per creator, over the profiled videos only. Re-run it when new
videos change the story; the result is committed like profiles (D17).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from askthe.core.answering import clean_description
from askthe.core.bio import (
    WORK_PHRASES,
    BioDraft,
    bio_material,
    bio_system_prompt,
    check_bio,
)
from askthe.core.interfaces import (
    DocKind,
    KnowledgeStore,
    LLMClient,
    LLMTask,
    SearchIndex,
    SearchQuery,
)
from askthe.core.models import Creator, CreatorBio
from askthe.core.profiling import normalise


@dataclass
class BioReport:
    bio: CreatorBio
    dropped: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


def make_bio(
    creator: Creator,
    store: KnowledgeStore,
    search: SearchIndex,
    llm: LLMClient,
    max_passages: int = 80,
) -> BioReport:
    videos = {v.id: v for v in store.list_videos(creator.slug) if store.get_profile(v.id)}
    if not videos:
        raise ValueError("no profiled videos: run segment and understand first")
    profiles = {vid: store.get_profile(vid) for vid in videos}
    segments = {vid: {s.id: s for s in store.get_segments(vid)} for vid in videos}

    # Passages where they talk about their own work: first the products named in
    # their config, by every name (the specific ones, so the cap can't crowd them
    # out), then their name and generic phrases.
    queries = [
        (name, 12)
        for g in creator.glossary
        if g.type.value == "product"
        for name in (g.name, *g.heard_as)
    ]
    queries += [(q, 8) for q in (creator.display_name, *WORK_PHRASES)]
    chosen: dict[str, None] = {}
    for q, limit in queries:
        hits = search.search(
            SearchQuery(text=q, creator_id=creator.slug, kinds=[DocKind.SEGMENT], limit=limit)
        )
        for h in hits:
            if h.video_id in videos and len(chosen) < max_passages:
                chosen.setdefault(h.doc_id)
    passages = [
        (videos[vid], segments[vid][doc_id])
        for doc_id in chosen
        for vid in [doc_id.rsplit(":", 1)[0]]
        if vid in segments and doc_id in segments[vid]
    ]
    passages.sort(key=lambda p: (p[0].published_at, p[1].index))

    result = llm.generate_structured(
        LLMTask.BIO,
        bio_system_prompt(creator),
        "Write the profile.",
        BioDraft,
        context=bio_material(list(videos.values()), profiles, passages),
    )
    texts = {
        v.platform_id: normalise(
            " ".join(s.text for s in segments[v.id].values())
            + " "
            + clean_description(v.description)
        )
        for v in videos.values()
    }
    summary, journey, ventures, dropped = check_bio(result.value, texts, creator.pronoun)
    bio = CreatorBio(
        summary=summary,
        journey=journey,
        ventures=ventures,
        model=result.model,
        generated_at=datetime.now(UTC),
    )
    return BioReport(bio=bio, dropped=dropped, usage=result.usage)
