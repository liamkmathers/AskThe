# AskThe

**Ask a creator's whole back catalogue a question, and get their own answer, quoted in their own words, with a link to the video they said it in.**

AskThe turns a niche creator's videos into a structured, searchable knowledge base of their verdicts and recommendations. Fans ask in plain language and get an answer grounded only in what the creator actually said, quoting their words and linking back to the source videos.

AskThe is a template. Each creator gets their own instance, framed around them and their subject:

- **Ask The Iron Snail**: men's clothing and gear (jackets, denim, boots). This is the first instance.
- Ask The *next creator*: same engine, new config, onboarded in days, not weeks.

## North Star

> **Every fan question gets the creator's own answer, in their own words, linked to the video they said it in.**

We measure it as the share of questions that are either answered correctly with a verified quote and a working link to its video, or correctly marked "not covered".

## Current phase

**Phase 1: Private prototype.** We're proving the assistant can answer 20 real fan questions from about 50 Iron Snail videos, with at least 18 correct and every answer quoting and linking its source videos. The prototype is private and for testing only. See [ROADMAP](docs/ROADMAP.md).

## Getting started

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run askthe check
```

```bash
uv run pytest
```

### Ingesting videos

```bash
uv run askthe fetch iron-snail
```

```bash
uv run askthe segment iron-snail
```

```bash
uv run askthe status iron-snail
```

Then profile the videos and ask questions with Claude (needs `ASKTHE_ANTHROPIC_API_KEY`, and `ASKTHE_OPENAI_API_KEY` for embeddings; locally the usual `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` also work. These steps cost money):

```bash
uv run askthe understand iron-snail
```

```bash
uv run askthe index iron-snail
```

To try the ask page locally (answers call the LLM): with the API keys set, build the database once (`uv run askthe segment iron-snail`, which restores the saved profiles, then `uv run askthe index iron-snail`), then run `uv run askthe serve iron-snail` and open http://127.0.0.1:8000. `serve` warns if the database is empty or a key is missing.

To build and run the test set (see [EVALUATION](docs/EVALUATION.md)): `askthe comments iron-snail` (needs YouTube, like `fetch`), then `askthe questions iron-snail` to list candidate fan questions, and `askthe eval iron-snail --label <name>` to score hybrid against full mode.

```bash
uv run askthe ask iron-snail "What's the best value t-shirt he's tested?"
```

`fetch` downloads metadata and transcripts for the videos listed in `creators/iron-snail.videos.txt` into `data/iron-snail/raw/`. It skips videos already fetched, so it's safe to re-run. `segment` rebuilds the database (`data/askthe.db`) from those raw files, restoring the video profiles saved in `data/iron-snail/profiles/`.

**YouTube blocks cloud servers**, so run `fetch` from a home connection. Every other stage works anywhere from the raw files. Transcripts can also come from files instead: set `use = "files"` under `[adapters.transcripts]` in `askthe.toml` and put `<video_id>.vtt`, `.srt` or `.txt` files in `data/transcripts/`.

`askthe check` validates `askthe.toml` and every creator in `creators/`, and builds the configured adapters. `askthe.toml` picks which implementation sits behind each interface (store, search, transcript source, LLM…); see [ARCHITECTURE](docs/ARCHITECTURE.md#swappable-components).

## Docs

| Doc | What it's for |
| --- | --- |
| [VISION](docs/VISION.md) | Why this exists, who it serves, the principles we don't bend |
| [ROADMAP](docs/ROADMAP.md) | Phases, the gate each must pass, Phase 1 milestones |
| [PROTOTYPE_SPEC](docs/PROTOTYPE_SPEC.md) | What Phase 1 must do, what it won't, how it's demoed |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | The pipeline, the swappable-component design, the recommended stack |
| [DATA_MODEL](docs/DATA_MODEL.md) | Creators, videos, segments, products, verdicts, and how opinions change over time |
| [EVALUATION](docs/EVALUATION.md) | How we know it works: the test set, scoring, profile and retrieval checks |
| [DECISIONS](docs/DECISIONS.md) | What we decided, why, and what we rejected |
| [RISKS_AND_QUESTIONS](docs/RISKS_AND_QUESTIONS.md) | What could go wrong, and what's still undecided |
| [CLAUDE.md](CLAUDE.md) | Rules for coding agents working in this repo |
