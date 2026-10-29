"""Stage 3: profile each video. Run `index` afterwards to make profiles searchable.

A profile describes a video (sections, entities, sponsor reads, the questions it
answers); it holds no opinions (D15). Videos already profiled by the current profiler
version are skipped unless forced, so the stage only pays for what changed. Each
profile is also saved to the profile archive, so rebuilding the database restores it
instead of paying for it again (D17).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from askthe.core.interfaces import (
    KnowledgeStore,
    LLMClient,
    LLMTask,
    ProfileArchive,
)
from askthe.core.models import Creator, Entity, ProfileRecord, Segment, Video, VideoProfile
from askthe.core.profiling import (
    PROFILE_PROMPT,
    PROFILER_VERSION,
    EntityResolver,
    ProfileDraft,
    profile_from_draft,
    profile_system_prompt,
    segments_fingerprint,
    video_context,
)


@dataclass
class UnderstandReport:
    profiled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)


def understand_videos(
    creator: Creator,
    store: KnowledgeStore,
    llm: LLMClient,
    platform_ids: list[str] | None = None,
    force: bool = False,
    on_progress: Callable[[str, str], None] = lambda video_id, status: None,
    archive: ProfileArchive | None = None,
) -> UnderstandReport:
    report = UnderstandReport()
    resolver = EntityResolver(creator, store.list_entities(creator.slug))
    system = profile_system_prompt(creator)
    for video in store.list_videos(creator.slug):
        if platform_ids is not None and video.platform_id not in platform_ids:
            continue
        existing = store.get_profile(video.id)
        segments = store.get_segments(video.id)
        if existing and existing.profiler_version == PROFILER_VERSION and not force:
            if archive and segments:  # profiles made before the archive existed
                saved = archive.load(creator.slug, video.platform_id)
                if saved is None or saved.profile != existing:
                    entities = [store.get_entity(i) for i in existing.entity_ids]
                    _archive(archive, creator, video, existing, entities, segments)
            report.skipped.append(video.id)
            continue
        if not segments:
            report.failed[video.id] = "no segments; run segment first"
            continue
        try:
            result = llm.generate_structured(
                LLMTask.UNDERSTAND,
                system,
                PROFILE_PROMPT,
                ProfileDraft,
                context=video_context(video, segments),
            )
        except Exception as e:  # noqa: BLE001 - one video failing never stops the others
            report.failed[video.id] = f"{type(e).__name__}: {e}"
            on_progress(video.id, f"failed: {report.failed[video.id]}")
            continue
        for k, n in result.usage.items():
            report.usage[k] = report.usage.get(k, 0) + n

        entities = [resolver.resolve(e) for e in result.value.entities]
        profile = profile_from_draft(video, result.value, entities, len(segments), result.model)
        for entity in entities:  # shared across videos: upserted, never replaced
            store.upsert_entity(entity)
        store.save_profile(profile)
        if archive:
            _archive(archive, creator, video, profile, entities, segments)

        report.profiled.append(video.id)
        on_progress(
            video.id,
            f"{len(profile.outline)} sections, {len(profile.passages)} passages, "
            f"{len(entities)} entities: {video.title}",
        )
    return report


def _archive(
    archive: ProfileArchive,
    creator: Creator,
    video: Video,
    profile: VideoProfile,
    entities: list[Entity | None],
    segments: list[Segment],
) -> None:
    archive.save(
        creator.slug,
        ProfileRecord(
            platform_id=video.platform_id,
            profile=profile,
            entities=[e for e in entities if e is not None],
            segments_fingerprint=segments_fingerprint(segments),
        ),
    )
