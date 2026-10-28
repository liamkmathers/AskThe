"""Command line. Pipeline stage commands (fetch, segment, extract, ...) land with their
milestones; see docs/ROADMAP.md."""

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
from askthe.wiring import build_services

app = typer.Typer(help="AskThe: a creator's back catalogue, answerable.", no_args_is_help=True)

ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="Path to askthe.toml.")]


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


if __name__ == "__main__":
    app()
