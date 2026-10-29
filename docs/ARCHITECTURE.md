# Architecture

How content gets from a creator's videos to a cited answer, and how the system is built so any part can be swapped later.

## Design rules

1. **Transcripts are the source of truth.** Raw fetched material is saved as files and never thrown away. Everything else (segments, extracted knowledge, search indexes, the database) is derived from those files and can be rebuilt.
2. **Reason at question time, from his actual words.** What matters in a video depends on the question, so nothing about his opinions is extracted in advance. Pre-processing describes videos (metadata, sections, sponsor reads) so the right ones are found and read well; the model reasons over the full transcripts when a question is asked. See [D15](DECISIONS.md#d15-reason-at-question-time-not-extraction-time).
3. **Every stage is re-runnable on its own.** Each stage reads the previous stage's saved output and writes its own. A better profile prompt or a new database means re-running from that stage, not re-downloading.
4. **Swappable by design.** Each external dependency sits behind a small interface. Which implementation is used is chosen in config. Swapping one is a new adapter plus a config change, never a pipeline change.
5. **Creator-agnostic engine.** Nothing in the engine assumes The Iron Snail, menswear, or YouTube. Creator specifics live in the creator's config file.
6. **Citations are verified in code.** The model proposes citations; code checks each one against the stored segments, and that each quote really appears there, before it reaches the user.
7. **No dependence on timestamps.** Transcripts are plain text; any source of a video's words works. See [D12](DECISIONS.md#d12-no-timestamps).

## The pipeline

```
YouTube ──▶ 1. Fetch ──▶ 2. Segment ──▶ 3. Understand ──▶ 4. Index ──▶ 5. Answer
            raw files    numbered        video profiles     search      reasoned over full
                         text chunks     (no opinions)      indexes     transcripts, quotes
                                                                        checked in code
```

### 1. Fetch

For each video, save metadata and the transcript as one raw file:

- **Metadata:** video ID, title, publish date, duration, description, chapters (if the creator added them), tags, view count, thumbnail URL.
- **Transcript:** the spoken text, plus which kind of captions it came from (creator-uploaded or auto-generated) and the language. Caption timing is discarded.

Output: `data/<creator>/raw/<video_id>.json`. Re-fetching skips videos already saved, unless forced.

Fetching needs network access to YouTube. If the environment blocks it, run this stage on a local machine and copy the `raw/` folder; every later stage works offline from those files.

### 2. Segment

- **Split** the transcript into ordered segments of roughly 120–200 words, ending at sentence ends where the captions have punctuation. Each segment keeps its position in the video.
- **Clean** obvious caption noise (repeated words, `[Music]` markers) without altering meaning.

This stage is mechanical. Understanding what the video is about happens in stage 3.

### 3. Understand

One LLM call per video reads the whole transcript and writes a **video profile**: a description of the video, not of his opinions.

- **What it is:** purpose, type (review, comparison, ranking, long-term review, explainer, how-to), thesis and key takeaways.
- **Sections:** the video's parts in order, following his own structure where there is one, each with a one-line summary and its segment range.
- **Entities:** products, components, materials, brands, services, people and concepts discussed, with names corrected from caption errors via the glossary, title and description. Names that can't be identified stay as said, never guessed.
- **Passages:** the intro, sponsor reads, asides (skits, jokes, personal life) and outro, each pinned to its exact first and last words, so it can be marked precisely inside the transcript, even mid-segment. Talk about his own products is not a sponsor read (D14).
- **Corrections**, **the questions it answers** (in a fan's words), **related videos**.

Profiles are versioned (`PROFILER_VERSION`) and re-run only when that changes. Cost in the first trial: about $0.19 per video.

### 4. Index

- **Store:** videos, segments, profiles and entities in SQLite.
- **Search** (SQLite FTS5) over three kinds of document: transcript segments, each video's profile text (title, purpose, thesis, sections, topics, entity names and aliases), and the questions each video answers.

Search is used to choose videos, not passages: the model reads whole transcripts.

### 5. Answer

1. **Choose videos.** If the whole catalogue fits the reading budget (`budget_words`, default 400,000 words; the 50-video prototype is about 150,000), read everything. Otherwise rank videos by search relevance and take the best that fit. Videos are ordered by date, so the same set produces the same input and is served from the prompt cache.
2. **Lay them out.** Each video is given with its title, publish date, type, purpose and sections, then its transcript as `[video_id:segment]` lines with passages marked inline (`«SPONSOR: ...» ... «END SPONSOR»`), and any corrections noted.
3. **Reason and answer.** The model answers this question from the transcripts, following the product rules (his opinion first, grounded or silent, newest first, attributed, sponsorship flagged, hedging kept), and cites every statement with a video, segment and exact quote.
4. **Verify.** Code checks every quote appears in the segment it cites. If any fail, the model gets one retry told which; whatever still fails is removed and reported, never repaired.
5. **Log** the question, answer, coverage and cited segments (feeds evaluation and the future creator dashboard).

First trial (22 videos, 112k tokens of transcript): about $0.60 for the first question, which writes the cache, then $0.03 to $0.06 per question.

## Swappable components

Each of these is an interface in the engine core, with implementations as adapters. The config file picks which adapter is used.

| Interface | Job | First implementation | Likely later swaps |
| --- | --- | --- | --- |
| `CatalogSource` | List a creator's videos and their metadata | yt-dlp | YouTube Data API; creator-supplied export |
| `TranscriptSource` | Get the transcript text for a video | youtube-transcript-api; or `files` (`.vtt`, `.srt`, `.txt`) | yt-dlp subtitles; Whisper on audio; a transcript service |
| `KnowledgeStore` | Save and query videos, segments, profiles, entities, answer logs | SQLite | Postgres |
| `SearchIndex` | Find relevant segments and claims for a query | SQLite full-text search (FTS5) | Hybrid with vectors; a dedicated search service |
| `Embedder` | Turn text into vectors (only once vectors are added) | none | Any embedding provider or local model |
| `LLMClient` | Structured extraction and answer generation | Anthropic API (Claude), model set in config | Other models or providers |

Rules for adapters:

- The core defines the interfaces and the domain models; adapters depend on the core, never the other way round.
- One place (the "composition root") reads config and wires adapters together. No other code constructs adapters directly.
- Domain models are plain data objects, not database rows or API responses. Adapters translate at the boundary.
- Each interface has a fake in-memory implementation for tests, so pipeline logic is tested without network, API keys or a real database.

## Recommended stack

| Concern | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12+ | Best tooling for transcripts, LLM SDKs and data work |
| Domain models and config validation | Pydantic | Typed models, validated config, JSON schemas for structured LLM output |
| LLM | Anthropic SDK, structured output via tool use | Reliable structured extraction; model name in config |
| Database | SQLite (with FTS5) | Zero setup, one file, plenty for ~50 videos |
| Web app | FastAPI with a minimal server-rendered chat page | Small, fast to build; UI can be replaced without touching the engine |
| Command line | Typer | `askthe fetch`, `segment`, `extract`, `index`, `ask`, `eval` |
| Tests | pytest | Fakes for every interface |
| Packaging | uv, `pyproject.toml` | Fast, reproducible installs |

## Repository layout (planned)

```
askthe/
  core/            domain models, interfaces, pure logic (no I/O)
  adapters/        sources/, storage/, search/, llm/, embeddings/
  pipeline/        fetch, segment, understand, ask
  app/             web chat (FastAPI)
  cli.py           command line
  wiring.py        composition root: config → adapters
creators/
  iron-snail.yaml  per-creator config
eval/
  questions/       test sets per creator
  runs/            saved evaluation results
data/              raw and derived data (git-ignored)
docs/
tests/
```

## Creator config

One file per creator, e.g. `creators/iron-snail.yaml`:

```yaml
slug: iron-snail
display_name: The Iron Snail
instance_name: Ask The Iron Snail
channel_url: https://www.youtube.com/@TheIronSnail
niche: men's clothing and gear
categories: [jackets, coats, fleece, denim, chinos, boots, shoes, knitwear,
             sweatshirts, t-shirts, shirts, underwear, accessories]
refer_to_creator_as: "The Iron Snail"   # how answers name the creator
pronoun: he                              # as the creator uses publicly
video_selection: creators/iron-snail.videos.txt   # the chosen ~50 video IDs
glossary:                                # known names and how captions mangle them
  - name: Uniqlo
    type: brand
    heard_as: [Unilo, Uniclo, Unic]
```

The glossary grows as videos are processed: entity resolution proposes entries, a person approves them. See [DATA_MODEL](DATA_MODEL.md#glossary).

Adding a creator means adding a config file and running the pipeline. No code changes.
