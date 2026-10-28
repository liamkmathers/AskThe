# Architecture

How content gets from a creator's videos to a cited answer, and how the system is built so any part can be swapped later.

## Design rules

1. **Transcripts are the source of truth.** Raw fetched material is saved as files and never thrown away. Everything else (segments, extracted knowledge, search indexes, the database) is derived from those files and can be rebuilt.
2. **Extraction is an index, not a replacement.** Extracted verdicts are how we *find* the right moment; the transcript around that moment is what answers are built from. Nuance the schema didn't anticipate survives.
3. **Every stage is re-runnable on its own.** Each stage reads the previous stage's saved output and writes its own. A better extraction prompt or a new database means re-running from that stage, not re-downloading.
4. **Swappable by design.** Each external dependency sits behind a small interface. Which implementation is used is chosen in config. Swapping one is a new adapter plus a config change, never a pipeline change.
5. **Creator-agnostic engine.** Nothing in the engine assumes The Iron Snail, menswear, or YouTube. Creator specifics live in the creator's config file.
6. **Citations are verified in code.** The model proposes citations; code checks each one against the stored segments, and that each quote really appears there, before it reaches the user.
7. **No dependence on timestamps.** Transcripts are plain text; any source of a video's words works. See [D12](DECISIONS.md#d12-no-timestamps).

## The pipeline

```
YouTube ──▶ 1. Fetch ──▶ 2. Segment ──▶ 3. Extract ──▶ 4. Index ──▶ 5. Answer
            raw files    segments +      claims +        search      cited
                         video type      products        indexes     answers
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

### 3. Understand and extract

Extraction is two passes, so the details are read in light of the whole video. A sentence means different things in a review, an explainer and a sponsor read.

**Pass A: understand the video.** An LLM reads the whole transcript with its metadata, the creator config and the creator's glossary, and writes a **video profile**:

- **Purpose:** what the video is for (help choose a boot, explain why a sole works, tell a brand's history, rank items for value).
- **Type:** review, comparison, ranking, long-term review, explainer, how-to, other.
- **Thesis and key takeaways:** the argument the creator is making, in a few sentences.
- **Outline:** named sections (as ranges of segments), so long videos that interleave several threads have structure even without chapters.
- **Topics and entities:** products (and specific versions, like "vintage, made in USA"), components, brands, materials, services, people and concepts covered. Names are corrected from caption errors using the glossary, the title and the **description**, which on gear channels usually lists the products shown. Names that still can't be identified are kept as said and marked unresolved, never guessed.
- **Segment roles:** which stretches are the main content, intro, sponsor read, aside (skits, jokes, personal life) or outro.
- **Corrections:** where the video corrects itself (an editor's note, "oops, I just remembered…").
- **Questions it answers:** the fan questions this video would be a good source for, in plain language ("Why do so many good boots use Vibram soles?", "What's the best value t-shirt?").
- **Uses:** how the knowledge helps a fan: a buying decision, care and maintenance, understanding how something works, background and history.

**Pass B: extract claims.** With the profile as context, the LLM goes through the main-content segments and records **claims**, each tied to the segment and quote it came from. See [DATA_MODEL](DATA_MODEL.md) for the full structure. In short:

- **His opinions first.** Every opinion and personal preference is captured, however brief or offhand, including what he says he wears himself. These are the most valuable claims in the system.
- A **fixed core** for verdicts: entity or version, the **aspect** being judged (value, quality, fit…), stance, pros and cons, good for and bad for, price with its type, buying and sizing advice. These are what we filter and compare on.
- **Who holds the view** (the creator, "people", a brand) and **how sure he is**, so reported views and hedges are never turned into his firm verdict.
- **Rankings**, **explanations, history, advice and techniques**, for knowledge that isn't a single verdict.
- **Mentions**, for things named without a verdict.
- **Open attributes** and an `other` kind, so nothing is forced into the wrong box.
- Claims from **sponsor segments** are always marked as sponsored and never treated as the creator's independent verdict.
- Claims overridden by an in-video correction are linked to the correction.
- **Nothing about the personal life** of the creator, family or friends is extracted.

Then **entity resolution** merges names across videos ("Iron Rangers", "the Red Wings", "Red Wing 8111") into one entity with aliases, giving each one a dated **timeline** of claims. It also proposes new glossary entries for a person to approve.

Every profile and claim records the extractor version and model that produced it. Changing the schema or prompts means re-running this stage over the saved segments.

### 4. Index

- **Structured store:** videos and their profiles, segments, entities, claims, in one database.
- **Text search** over segments, claims and each video's "questions it answers", so a fan's wording can match the questions a video was profiled as answering.
- **Vector search** is *not* in the first version. It's added behind the same search interface if the evaluation shows text search missing questions.

### 5. Answer

1. **Understand the question:** pull out products, categories, constraints (price, conditions) and question type (lookup, comparison, change of mind, how-to).
2. **Retrieve:** structured lookups over claims, text search over segments, and matching against video profiles. For each hit, include the surrounding transcript and the video's purpose and thesis, not just the claim.
3. **Decide coverage:** if nothing relevant is retrieved, the answer is "not covered", by design. The model is not asked to answer without evidence.
4. **Compose:** the LLM writes the answer from the retrieved evidence only, citing evidence IDs. It leads with the newest verdict and states changes of opinion.
5. **Verify:** code checks each cited ID exists, maps to a real video and segment, and that each quoted phrase appears in that segment; then it turns the citation into the video title, date, quote and a link (`https://www.youtube.com/watch?v=<id>`). Answers with unverifiable citations are rejected or regenerated.
6. **Log:** question, answer, citations and coverage are recorded (feeds evaluation and the future creator dashboard).

## Swappable components

Each of these is an interface in the engine core, with implementations as adapters. The config file picks which adapter is used.

| Interface | Job | First implementation | Likely later swaps |
| --- | --- | --- | --- |
| `CatalogSource` | List a creator's videos and their metadata | yt-dlp | YouTube Data API; creator-supplied export |
| `TranscriptSource` | Get the transcript text for a video | youtube-transcript-api; or `files` (`.vtt`, `.srt`, `.txt`) | yt-dlp subtitles; Whisper on audio; a transcript service |
| `KnowledgeStore` | Save and query videos, profiles, segments, entities, claims | SQLite | Postgres |
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
  pipeline/        fetch, segment, understand, extract, resolve, index stages
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
