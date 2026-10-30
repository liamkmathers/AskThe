"""Command line: one command per pipeline stage, plus checks. See docs/ARCHITECTURE.md."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml

from askthe.config import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    channel_path,
    list_creator_slugs,
    load_app_config,
    load_creator,
    load_questions,
    load_video_selection,
)
from askthe.core.answering import WATCH_URLS
from askthe.core.models import Creator
from askthe.core.questions import question_candidates
from askthe.pipeline.ask import RetrievalSettings, ask
from askthe.pipeline.comments import fetch_comments
from askthe.pipeline.evaluate import rescore, run_eval
from askthe.pipeline.fetch import fetch_videos
from askthe.pipeline.index import index_videos
from askthe.pipeline.segment import segment_videos
from askthe.pipeline.understand import understand_videos
from askthe.wiring import PORTS, Services, build_services

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
    for port in PORTS:
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
    limit: Annotated[
        int | None, typer.Option(help="Fetch at most this many videos not yet fetched.")
    ] = None,
    delay: Annotated[
        float, typer.Option(help="Seconds to wait between videos (12 = 5 videos a minute).")
    ] = 12.0,
    stop_after: Annotated[
        int, typer.Option(help="Stop after this many failures in a row (likely rate-limited).")
    ] = 3,
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Stage 1: fetch metadata and transcripts into the raw archive. Re-runnable."""
    services, c = _setup(config_path, creator)
    if video:
        ids = list(video)
    elif channel:
        ids = [v.platform_id for v in services.catalog.list_videos(c)]
    else:
        ids = load_video_selection(services.config, c)
    if limit is not None:  # count only videos still to fetch
        ids = [v for v in ids if not services.raw_archive.has(c.slug, v)][:limit]
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
        max_consecutive_failures=stop_after,
        on_progress=lambda vid, status: typer.echo(f"{vid}  {status}"),
    )
    typer.echo(
        f"fetched {len(report.fetched)}, skipped {len(report.skipped)}, failed {len(report.failed)}"
    )
    if report.stopped_early:
        typer.echo(
            f"stopped after {stop_after} failures in a row: probably rate-limited. "
            "Wait an hour or so and run fetch again; fetched videos are kept and skipped."
        )
    if report.failed:
        raise typer.Exit(1)


@app.command()
def comments(
    creator: CreatorArg,
    video: Annotated[
        list[str] | None,
        typer.Option("--video", "-v", help="These video IDs instead of the selection file."),
    ] = None,
    per_video: Annotated[int, typer.Option(help="Top comments to keep per video.")] = 300,
    limit: Annotated[
        int | None, typer.Option(help="At most this many videos not yet done.")
    ] = None,
    delay: Annotated[float, typer.Option(help="Seconds to wait between videos.")] = 12.0,
    stop_after: Annotated[
        int, typer.Option(help="Stop after this many failures in a row (likely rate-limited).")
    ] = 3,
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Fetch viewers' top comments into the raw archive, for the test set. Needs YouTube."""
    services, c = _setup(config_path, creator)
    ids = list(video) if video else load_video_selection(services.config, c)
    if limit is not None:  # count only videos still to do
        ids = [v for v in ids if not services.raw_archive.has_comments(c.slug, v)][:limit]
    if not ids:
        typer.echo("no videos: add IDs to the selection file, or use --video")
        raise typer.Exit(1)
    report = fetch_comments(
        c,
        ids,
        services.comments,
        services.raw_archive,
        source_name=services.config.adapters["comments"].use,
        per_video=per_video,
        delay_s=delay,
        max_consecutive_failures=stop_after,
        on_progress=lambda vid, status: typer.echo(f"{vid}  {status}"),
    )
    typer.echo(
        f"fetched comments for {len(report.fetched)} videos, skipped {len(report.skipped)}, "
        f"failed {len(report.failed)}"
    )
    if report.stopped_early:
        typer.echo(
            f"stopped after {stop_after} failures in a row: probably rate-limited. "
            "Run again later; videos already done are skipped."
        )
    if report.failed:
        raise typer.Exit(1)


@app.command()
def questions(
    creator: CreatorArg,
    out: Annotated[
        Path | None,
        typer.Option(help="Where to write. Default: eval/questions/<creator>.candidates.yaml"),
    ] = None,
    top: Annotated[int, typer.Option(help="Keep the most liked this many.")] = 150,
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Pick question-like comments from fetched comments, for choosing the test set."""
    services, c = _setup(config_path, creator)
    archive = services.raw_archive
    batches = [archive.load_comments(c.slug, pid) for pid in archive.list_comment_ids(c.slug)]
    if not batches:
        typer.echo("no comments fetched yet: run `askthe comments` where YouTube is reachable")
        raise typer.Exit(1)
    titles = {
        pid: archive.load(c.slug, pid).meta.title
        for pid in archive.list_comment_ids(c.slug)
        if archive.has(c.slug, pid)
    }
    watch = WATCH_URLS[c.platform]
    found = question_candidates(
        batches, titles, {b.platform_id: watch.format(b.platform_id) for b in batches}
    )
    kept = found[:top]
    path = out or services.config.eval_dir / "questions" / f"{c.slug}.candidates.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Question-like comments on {len(batches)} videos, most liked first "
        f"({len(kept)} of {len(found)}).\n"
        "# Generated by `askthe questions`; pick the test set from these into "
        f"{c.slug}.yaml.\n"
    )
    path.write_text(
        header
        + yaml.safe_dump(
            [q.model_dump() for q in kept], sort_keys=False, allow_unicode=True, width=100
        )
    )
    requests = sum(q.kind == "request" for q in kept)
    typer.echo(f"wrote {len(kept)} candidates ({requests} requests for videos) to {path}")


@app.command()
def channel(creator: CreatorArg, config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """Fetch the channel's name, description, avatar and banner for the creator page.
    Needs YouTube, like fetch; saves data/<creator>/channel.json (commit it)."""
    services, c = _setup(config_path, creator)
    info = services.catalog.get_channel(c)
    path = channel_path(services.config, c.slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(info.model_dump_json(indent=2) + "\n")
    subs = f"{info.subscribers:,} subscribers" if info.subscribers else "subscribers unknown"
    typer.echo(f"{info.title}: {subs}, avatar {'found' if info.avatar_url else 'missing'}")
    typer.echo(f"saved {path}")


@app.command()
def videos(creator: CreatorArg, config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """List the creator's videos (newest first) as tab-separated id, minutes, title.

    Marks with * the videos already in the selection file.
    """
    services, c = _setup(config_path, creator)
    selected = set(load_video_selection(services.config, c))
    for v in services.catalog.list_videos(c):
        minutes = f"{v.duration_s / 60:.0f}" if v.duration_s else "?"
        mark = "*" if v.platform_id in selected else " "
        typer.echo(f"{mark}{v.platform_id}\t{minutes}\t{v.title}")


@app.command()
def segment(creator: CreatorArg, config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """Stage 2: rebuild videos and segments from the raw archive, and index them."""
    services, c = _setup(config_path, creator)
    report = segment_videos(c, services.raw_archive, services.store, profiles=services.profiles)
    typer.echo(
        f"segmented {report.videos} videos into {report.segments} segments; "
        f"restored {report.restored} saved profiles"
    )
    if report.stale:
        typer.secho(
            f"{len(report.stale)} saved profiles no longer match their segments; "
            "run understand to redo them",
            fg=typer.colors.YELLOW,
        )


@app.command()
def understand(
    creator: CreatorArg,
    video: Annotated[
        list[str] | None, typer.Option("--video", "-v", help="Only these video IDs.")
    ] = None,
    limit: Annotated[int | None, typer.Option(help="Profile at most this many videos.")] = None,
    force: Annotated[
        bool, typer.Option(help="Re-profile videos already done by this profiler version.")
    ] = False,
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Stage 3: profile each video (sections, entities, sponsor reads). Calls the LLM."""
    services, c = _setup(config_path, creator)
    ids = list(video) if video else None
    if limit is not None:
        ids = [
            v.platform_id
            for v in services.store.list_videos(c.slug)
            if (ids is None or v.platform_id in ids) and not services.store.get_profile(v.id)
        ][:limit]
    report = understand_videos(
        c,
        services.store,
        services.llm,
        platform_ids=ids,
        force=force,
        on_progress=lambda vid, msg: typer.echo(f"{vid}  {msg}"),
        archive=services.profiles,
    )
    typer.echo(
        f"profiled {len(report.profiled)}, skipped {len(report.skipped)}, "
        f"failed {len(report.failed)}"
    )
    if report.usage:
        typer.echo("tokens: " + ", ".join(f"{k} {n:,}" for k, n in report.usage.items()))
    if report.failed:
        raise typer.Exit(1)


@app.command(name="index")
def index_command(creator: CreatorArg, config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """Stage 4: build keyword and vector search. Embeds only what changed."""
    services, c = _setup(config_path, creator)
    report = index_videos(c, services.store, services.search, services.vectors, services.embedder)
    typer.echo(
        f"indexed {report.videos} videos, {report.documents} documents "
        f"({report.embedded} embedded, {report.unchanged} unchanged)"
    )
    if report.unprofiled:
        typer.echo(f"{len(report.unprofiled)} videos have no profile yet; run understand")
    for warning in report.warnings:
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW)


@app.command(name="ask")
def ask_command(
    creator: CreatorArg,
    question: Annotated[str, typer.Argument(help="The fan's question, in plain language.")],
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Answer a question from the creator's videos, with verified quotes. Calls the LLM."""
    services, c = _setup(config_path, creator)
    result = ask(
        c,
        question,
        services.store,
        services.search,
        services.llm,
        vectors=services.vectors,
        embedder=services.embedder,
        settings=RetrievalSettings.from_config(services.config.retrieval),
    )
    a = result.answer
    typer.echo(a.text)
    if a.sources:
        typer.echo("\nSources:")
        for s in sorted(a.sources, key=lambda s: s.n):
            typer.echo(f'[{s.n}] {s.title} ({s.published}) {s.url}\n    "{s.quote}"')
    t = result.trace
    typer.echo(
        f"\ncoverage: {a.coverage.value} | {t['mode']} retrieval: read "
        f"{len(result.videos_read)} videos, {t.get('context_words', 0):,} words"
        + (f" ({t['kept']} of {t['candidates']} candidates kept)" if "kept" in t else "")
    )
    for warning in t.get("warnings", []):
        typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW)
    if a.problems:
        typer.secho("unverified citations removed:", fg=typer.colors.YELLOW)
        for problem in a.problems:
            typer.echo(f"  {problem}")
    if result.usage:
        typer.echo("tokens: " + ", ".join(f"{k} {n:,}" for k, n in result.usage.items()))


@app.command(name="eval")
def eval_command(
    creator: CreatorArg,
    mode: Annotated[
        list[str] | None,
        typer.Option(
            "--mode",
            "-m",
            help="Retrieval modes to run, in order. Default: hybrid. Add full as a reference.",
        ),
    ] = None,
    label: Annotated[str, typer.Option(help="Names the saved run.")] = "run",
    questions_file: Annotated[
        Path | None,
        typer.Option("--questions", help="Test set. Default: eval/questions/<creator>.yaml"),
    ] = None,
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Run only these question ids.")
    ] = None,
    rescore_run: Annotated[
        Path | None,
        typer.Option(
            "--rescore", help="Re-check a saved run against the current test set; no LLM calls."
        ),
    ] = None,
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Run the test set, score every answer, and save the run to eval/runs/. Calls the LLM."""
    services, c = _setup(config_path, creator)
    eval_dir = services.config.eval_dir
    try:
        test_set = load_questions(questions_file or eval_dir / "questions" / f"{c.slug}.yaml")
    except ConfigError as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None
    if only:
        test_set = [q for q in test_set if q.id in only]
    modes = list(mode) if mode else ["hybrid"]

    if rescore_run:
        run = rescore(json.loads(rescore_run.read_text()), test_set, c.pronoun)
        out = rescore_run.with_name(rescore_run.stem + "-rescored.json")
        out.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n")
        _print_summary(run)
        typer.echo(f"rescored {len(run['questions'])} questions into {out}")
        return

    def progress(qid: str, m: str, r: dict) -> None:
        ok = "pass" if r["checks"]["passed"] else "FAIL"
        dollars = f"${r['cost_usd']:.3f}" if r["cost_usd"] is not None else "$?"
        typer.echo(
            f"{qid:<6} {m:<7} {ok}  {r['coverage']:<8} {len(r['sources']):>2} cites  "
            f"{r['context_words']:>6,} words  {len(r['videos_read']):>2} videos  {dollars}"
        )

    run = run_eval(
        c,
        test_set,
        modes,
        services.store,
        services.search,
        services.llm,
        services.vectors,
        services.embedder,
        RetrievalSettings.from_config(services.config.retrieval),
        services.config.prices,
        label,
        on_progress=progress,
    )
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    path = eval_dir / "runs" / f"{stamp}-{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n")
    _print_summary(run)
    typer.echo(f"saved {path}; mark each answer's `correct` after reading it")


def _print_summary(run: dict) -> None:
    for m, s in run["summary"].items():
        typer.echo(
            f"{m}: {s['passed_checks']}/{s['questions']} passed automated checks, "
            f"coverage right {s['coverage_right']}, citations hold {s['citations_hold']}, "
            f"personal life {s.get('personal_life', 0)}, "
            f"mean {s['mean_context_words']:,} words, "
            + (
                f"expected videos read {s['expected_sources_read']:.0%}, "
                if s.get("expected_sources_read") is not None
                else ""
            )
            + (f"${s['cost_usd']:.2f}" if s["cost_usd"] is not None else "cost unknown")
            + (
                f", recall of full {s['mean_recall_of_full']:.0%}"
                if s.get("mean_recall_of_full") is not None
                else ""
            )
        )


def _serve_problems(services: Services, c: Creator) -> list[str]:
    """What would stop the page answering: an empty database, or missing API keys."""
    import os

    problems = []
    videos = services.store.list_videos(c.slug)
    if not videos:
        problems.append(
            f"no videos in the database: run `askthe segment {c.slug}` then `askthe index {c.slug}`"
        )
    elif not any(services.store.get_profile(v.id) for v in videos):
        problems.append(f"no profiles loaded: run `askthe segment {c.slug}` (restores saved ones)")
    else:
        unprofiled = sum(1 for v in videos if not services.store.get_profile(v.id))
        if unprofiled and services.config.retrieval.get("require_profiles"):
            problems.append(
                f"{unprofiled} videos have no profile and won't be used in answers "
                f"until `askthe understand {c.slug}` profiles them"
            )
    adapters = services.config.adapters
    keys = {
        "llm": ("anthropic", ("ASKTHE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")),
        "embedder": ("openai", ("ASKTHE_OPENAI_API_KEY", "OPENAI_API_KEY")),
    }
    for port, (adapter, names) in keys.items():
        if adapters[port].use == adapter and not any(os.environ.get(n) for n in names):
            problems.append(f"no API key for {port}: set {' or '.join(names)}")
    return problems


@app.command()
def serve(
    creator: CreatorArg,
    host: Annotated[str, typer.Option(help="Address to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
    config_path: ConfigOption = DEFAULT_CONFIG_PATH,
) -> None:
    """Run the ask page (docs/UI_PLAN.md) for one creator. Answers call the LLM."""
    import uvicorn

    from askthe.app.server import create_app

    services, c = _setup(config_path, creator)
    settings = RetrievalSettings.from_config(services.config.retrieval)
    for problem in _serve_problems(services, c):
        typer.secho(f"warning: {problem}", fg=typer.colors.YELLOW)
    typer.echo(f"{c.instance_name}: http://{host}:{port}")
    uvicorn.run(create_app(services, c, settings), host=host, port=port, log_level="warning")


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
    profiled = sum(1 for v in videos if services.store.get_profile(v.id))
    saved = len(services.profiles.list_ids(c.slug))
    typer.echo(f"{'profiled':<12} {profiled} videos ({saved} profiles saved)")


if __name__ == "__main__":
    app()
