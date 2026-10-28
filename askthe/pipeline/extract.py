"""Stage 3: understand each video, extract its claims, and index them.

Videos already extracted by the current extractor version are skipped unless forced,
so the stage is safe to re-run and only pays for what changed. Everything it writes is
derived and replaced per video.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from askthe.core.extraction import (
    EXTRACTOR_VERSION,
    UNDERSTAND_PROMPT,
    ClaimsDraft,
    EntityResolver,
    ProfileDraft,
    claims_from_drafts,
    extract_prompt,
    profile_from_draft,
    profile_summary,
    system_prompt,
    video_context,
    windows,
)
from askthe.core.interfaces import (
    DocKind,
    KnowledgeStore,
    LLMClient,
    LLMTask,
    SearchDoc,
    SearchIndex,
)
from askthe.core.models import Claim, Creator, Video, VideoProfile


@dataclass
class VideoExtraction:
    video_id: str
    claims: int = 0
    rejected: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ExtractReport:
    extracted: list[VideoExtraction] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for v in self.extracted:
            for k, n in v.usage.items():
                total[k] = total.get(k, 0) + n
        return total


def extract_videos(
    creator: Creator,
    store: KnowledgeStore,
    search: SearchIndex,
    llm: LLMClient,
    platform_ids: list[str] | None = None,
    force: bool = False,
    window_size: int = 8,
    on_progress: Callable[[str, str], None] = lambda video_id, status: None,
) -> ExtractReport:
    report = ExtractReport()
    resolver = EntityResolver(creator, store.list_entities(creator.slug))
    system = system_prompt(creator)
    for video in store.list_videos(creator.slug):
        if platform_ids is not None and video.platform_id not in platform_ids:
            continue
        existing = store.get_profile(video.id)
        if existing and existing.extractor_version == EXTRACTOR_VERSION and not force:
            report.skipped.append(video.id)
            continue
        try:
            result = _extract_one(video, store, search, llm, resolver, system, window_size)
        except Exception as e:  # noqa: BLE001 - one video failing never stops the others
            report.failed[video.id] = f"{type(e).__name__}: {e}"
            on_progress(video.id, f"failed: {report.failed[video.id]}")
            continue
        report.extracted.append(result)
        on_progress(
            video.id,
            f"{result.claims} claims, {len(result.rejected)} rejected: {video.title}",
        )
    return report


def _extract_one(
    video: Video,
    store: KnowledgeStore,
    search: SearchIndex,
    llm: LLMClient,
    resolver: EntityResolver,
    system: str,
    window_size: int,
) -> VideoExtraction:
    result = VideoExtraction(video_id=video.id)

    def add_usage(u: dict[str, int]) -> None:
        for k, n in u.items():
            result.usage[k] = result.usage.get(k, 0) + n

    segments = store.get_segments(video.id)
    if not segments:
        raise ValueError("video has no segments; run segment first")
    context = video_context(video, segments)

    # Pass A: understand the video as a whole.
    understood = llm.generate_structured(
        LLMTask.UNDERSTAND, system, UNDERSTAND_PROMPT, ProfileDraft, context=context
    )
    add_usage(understood.usage)
    entities = [resolver.resolve(e) for e in understood.value.entities]
    profile, roles = profile_from_draft(
        video, understood.value, entities, len(segments), understood.model
    )
    segments = [s.model_copy(update={"role": roles.get(s.index)}) for s in segments]

    # Pass B: claims, a window at a time, with the whole video and profile as context.
    summary = profile_summary(profile, entities)
    claims, versions = [], []
    for window in windows(segments, window_size):
        drafted = llm.generate_structured(
            LLMTask.EXTRACT,
            system,
            extract_prompt(summary, window, roles),
            ClaimsDraft,
            context=context,
        )
        add_usage(drafted.usage)
        in_window = {s.index for s in window}
        drafts = [d for d in drafted.value.claims if d.segment in in_window]
        result.rejected += [
            f"cited segment {d.segment} outside window"
            for d in drafted.value.claims
            if d.segment not in in_window
        ]
        build = claims_from_drafts(
            video, drafts, segments, roles, resolver, drafted.model, first_index=len(claims)
        )
        claims += build.claims
        versions += build.versions
        result.rejected += build.rejected

    # Save. Entities are shared across videos, so they're upserted, never replaced.
    for entity in resolver.entities.values():
        store.upsert_entity(entity)
    for version in versions:
        store.upsert_version(version)
    store.replace_segments(video.id, segments)
    store.save_profile(profile.model_copy(update={"entity_ids": _entity_ids(profile, claims)}))
    store.replace_claims(video.id, claims)

    # Re-index the whole video so stale claims from an earlier extraction disappear.
    search.remove_video(video.id)
    search.index(
        [
            SearchDoc(
                id=s.id,
                kind=DocKind.SEGMENT,
                creator_id=video.creator_id,
                video_id=video.id,
                text=s.text,
            )
            for s in segments
        ]
        + [
            SearchDoc(
                id=c.id,
                kind=DocKind.CLAIM,
                creator_id=video.creator_id,
                video_id=video.id,
                text=" ".join(
                    [
                        c.statement,
                        c.quote,
                        *(resolver.entities[e].canonical_name for e in c.entity_ids),
                    ]
                ),
            )
            for c in claims
        ]
        + [
            SearchDoc(
                id=f"{video.id}:q{i:03d}",
                kind=DocKind.PROFILE_QUESTION,
                creator_id=video.creator_id,
                video_id=video.id,
                text=question,
            )
            for i, question in enumerate(profile.answers_questions)
        ]
    )
    result.claims = len(claims)
    return result


def _entity_ids(profile: VideoProfile, claims: list[Claim]) -> list[str]:
    return list(dict.fromkeys([*profile.entity_ids, *(e for c in claims for e in c.entity_ids)]))
