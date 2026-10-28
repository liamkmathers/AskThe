"""Command line: one command per pipeline stage, plus checks. See docs/ARCHITECTURE.md."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from askthe.config import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    list_creator_slugs,
    load_app_config,
    load_creator,
    load_video_selection,
)
from askthe.core.models import Creator
from askthe.pipeline.fetch import fetch_videos
from askthe.pipeline.segment import segment_videos
from askthe.wiring import Services, build_services

app = typer.Typer(help="AskThe: a creator's back catalogue, answerable.", no_args_is_help=True)

ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="Path to askthe.toml.")]
CreatorArg = Annotated[str, typer.Argument(help="Creator slug: the name of its file in creators/.")]


def _setup(config_path: Path, slug: str) -> tuple[Services, Creator]:
    try:
        config = load_app_config(config_path)
        return build_services(config), load_creator(config, slug)
    except ConfigError as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None


@app.command()
def check(config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """Validate the config and every creator, and build the configured adapters."""
    try:
        config = load_app_config(config_path)
        services = build_services(config)
        slugs = list_creator_slugs(config)
        creators = [load_creator(config, slug) for slug in slugs]
        selections = {c.slug: load_video_selection(config, c) for c in creators}
    except ConfigError as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None

    typer.echo(f"{'config':<12} {config_path}")
    typer.echo(f"{'data dir':<12} {config.data_dir}")
    for port in ("catalog", "transcripts", "raw_archive", "store", "search", "llm"):
        adapter = getattr(services, port)
        typer.echo(f"{port:<12} {config.adapters[port].use} ({type(adapter).__name__})")
    if not creators:
        typer.echo("no creators configured")
    for creator in creators:
        typer.echo(
            f"{'creator':<12} {creator.instance_name} [{creator.slug}]: "
            f"{len(creator.categories)} categories, {len(creator.glossary)} glossary entries, "
            f"{len(selections[creator.slug])} selected videos"
        )
    typer.secho("ok", fg=typer.colors.GREEN)


@app.command()
def creators(config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """List configured creators."""
    try:
        config = load_app_config(config_path)
        for slug in list_creator_slugs(config):
            creator = load_creator(config, slug)
            typer.echo(f"{creator.slug:<20} {creator.instance_name}  ({creator.channel_url})")
    except ConfigError as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None


@app.command()
def fetch(
    creator: CreatorArg,
    video: Annotated[
        list[str] | None,
        typer.Option("--video", "-v", help="Fetch these video IDs instead of the selection file."),
    ] = None,
    channel: Annotated[
        bool, typer.Option("--channel", help="Fetch every video on the channel.")
    ] = False,
    limit: Annotated[int | None, typer.Option(help="Fetch at most this many videos.")] = None,
    delay: Annotated[float, typer.Option(help="Seconds to wait between videos.")] = 2.0,
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Stage 1: fetch metadata and transcripts into the raw archive. Re-runnable."""
    services, c = _setup(config_path, creator)
    if video:
        ids = list(video)
    elif channel:
        ids = services.catalog.list_video_ids(c)
    else:
        ids = load_video_selection(services.config, c)
    ids = ids[:limit] if limit is not None else ids
    if not ids:
        typer.echo("no videos to fetch: add IDs to the selection file, or use --video/--channel")
        raise typer.Exit(1)

    adapters = services.config.adapters
    report = fetch_videos(
        c,
        ids,
        services.catalog,
        services.transcripts,
        services.raw_archive,
        source=f"{adapters['catalog'].use}+{adapters['transcripts'].use}",
        delay_s=delay,
        on_progress=lambda vid, status: typer.echo(f"{vid}  {status}"),
    )
    typer.echo(
        f"fetched {len(report.fetched)}, skipped {len(report.skipped)}, failed {len(report.failed)}"
    )
    if report.failed:
        raise typer.Exit(1)


@app.command()
def segment(creator: CreatorArg, config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """Stage 2: rebuild videos and segments from the raw archive, and index them."""
    services, c = _setup(config_path, creator)
    report = segment_videos(c, services.raw_archive, services.store, services.search)
    typer.echo(f"segmented {report.videos} videos into {report.segments} segments")


@app.command()
def status(creator: CreatorArg, config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """Show what has been fetched and built for a creator."""
    services, c = _setup(config_path, creator)
    selected = load_video_selection(services.config, c)
    raw_ids = services.raw_archive.list_ids(c.slug)
    videos = services.store.list_videos(c.slug)
    segments = sum(len(services.store.get_segments(v.id)) for v in videos)
    missing = [v for v in selected if v not in raw_ids]
    typer.echo(f"{c.instance_name} [{c.slug}]")
    typer.echo(f"{'selected':<12} {len(selected)} videos")
    typer.echo(f"{'fetched':<12} {len(raw_ids)} raw videos ({len(missing)} selected not yet)")
    typer.echo(f"{'segmented':<12} {len(videos)} videos, {segments} segments")


if __name__ == "__main__":
    app()
