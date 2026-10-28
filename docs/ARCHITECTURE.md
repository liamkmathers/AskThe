# Architecture

How content gets from a creator's videos to a cited answer, and how the system is built so any part can be swapped later.

## Design rules

1. **Transcripts are the source of truth.** Raw fetched material is saved as files and never thrown away. Everything else (segments, extracted knowledge, search indexes, the database) is derived from those files and can be rebuilt.
2. **Extraction is an index, not a replacement.** Extracted verdicts are how we *find* the right moment; the transcript around that moment is what answers are built from. Nuance the schema didn't anticipate survives.
3. **Every stage is re-runnable on its own.** Each stage reads the previous stage's saved output and writes its own. A better extraction prompt or a new database means re-running from that stage, not re-downloading.
4. **Swappable by design.** Each external dependency sits behind a small interface. Which implementation is used is chosen in config. Swapping one is a new adapter plus a config change, never a pipeline change.
5. **Creator-agnostic engine.** Nothing in the engine assumes The Iron Snail, menswear, or YouTube. Creator specifics live in the creator's config file.
6. **Citations are verified in code.** The model proposes citations; code checks each one against stored timestamps before it reaches the user.

## The pipeline

```
YouTube ──▶ 1. Fetch ──▶ 2. Segment ──▶ 3. Extract ──▶ 4. Index ──▶ 5. Answer
            raw files    segments +      claims +        search      cited
                         video type      products        indexes     answers
```

### 1. Fetch

For each video, save metadata and the timestamped transcript as one raw file:

- **Metadata:** video ID, title, publish date, duration, description, chapters (if the creator added them), tags, view count, thumbnail URL.
- **Transcript:** caption fragments with start time and duration, plus which kind of captions they were (creator-uploaded or auto-generated) and the language.

Output: `data/<creator>/raw/<video_id>.json`. Re-fetching skips videos already saved, unless forced.

Fetching needs network access to YouTube. If the environment blocks it, run this stage on a local machine and copy the `raw/` folder; every later stage works offline from those files.

### 2. Segment and classify

- **Merge** caption fragments into segments of roughly 30–60 seconds, breaking at chapter boundaries and sentence ends where possible. Each segment keeps its start and end time.
- **Clean** obvious caption noise (repeated words, `[Music]` markers) without altering meaning.
- **Classify the video:** its type (review, comparison, buying guide, long-term review, how-to, other) and which of the creator's product categories it covers. Type matters later: a long-term review is stronger evidence about durability than a first impression.

### 3. Extract

An LLM reads each video, segment by segment with the video's metadata as context, and records **claims**, each tied to the segment and quote it came from. See [DATA_MODEL](DATA_MODEL.md) for the full structure. In short:

- A **fixed core** for product verdicts (product, stance, pros and cons, good for and bad for, price), because these are what we filter and compare on.
- **Open attributes** for anything else the creator says about a product (fit, materials, where it's made, what it pairs with).
- **Non-product claims** (advice, techniques, brand opinions, buying principles), with an `other` type so nothing is forced into the wrong box.
- A short **video summary**.

Then **product resolution** merges mentions across videos ("Iron Rangers", "the Red Wings", "Red Wing 8111") into one product with aliases, giving each product a dated **timeline** of verdicts.

Every extracted item records the extractor version and model that produced it. Changing the schema or prompt means re-running this stage over the saved segments.

### 4. Index

- **Structured store:** videos, segments, products, claims, in one database.
- **Text search** over segments and claims.
- **Vector search** is *not* in the first version. It's added behind the same search interface if the evaluation shows text search missing questions.

### 5. Answer

1. **Understand the question:** pull out products, categories, constraints (price, conditions) and question type (lookup, comparison, change of mind, how-to).
2. **Retrieve:** structured lookups over claims plus text search over segments. For each hit, include the surrounding transcript, not just the claim.
3. **Decide coverage:** if nothing relevant is retrieved, the answer is "not covered", by design. The model is not asked to answer without evidence.
4. **Compose:** the LLM writes the answer from the retrieved evidence only, citing evidence IDs. It leads with the newest verdict and states changes of opinion.
5. **Verify:** code checks each cited ID exists and maps to a real video and timestamp, then turns it into a link (`https://youtu.be/<id>?t=<seconds>`). Answers with unverifiable citations are rejected or regenerated.
6. **Log:** question, answer, citations and coverage are recorded (feeds evaluation and the future creator dashboard).

## Swappable components

Each of these is an interface in the engine core, with implementations as adapters. The config file picks which adapter is used.

| Interface | Job | First implementation | Likely later swaps |
| --- | --- | --- | --- |
| `CatalogSource` | List a creator's videos and their metadata | yt-dlp | YouTube Data API; creator-supplied export |
| `TranscriptSource` | Get a timestamped transcript for a video | youtube-transcript-api | yt-dlp subtitles; Whisper on audio; creator-supplied files |
| `KnowledgeStore` | Save and query videos, segments, products, claims | SQLite | Postgres |
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
  pipeline/        fetch, segment, extract, resolve, index stages
  answering/       question parsing, retrieval, composition, citation check
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
categories: [jackets, coats, denim, boots, shoes, knitwear, shirts, accessories]
refer_to_creator_as: "The Iron Snail"   # how answers name the creator
pronoun: he                              # as the creator uses publicly
video_selection: creators/iron-snail.videos.txt   # the chosen ~50 video IDs
```

Adding a creator means adding a config file and running the pipeline. No code changes.
