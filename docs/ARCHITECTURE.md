# Architecture

How content gets from a creator's videos to a cited answer, and how the system is built so any part can be swapped later.

## Design rules

1. **Transcripts are the source of truth.** Raw fetched material is saved as files and never thrown away. Everything else (segments, profiles, search indexes, the database) is derived from those files and can be rebuilt. Profiles are also committed as files, because each costs a model call to remake (D17).
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

Profiles are versioned (`PROFILER_VERSION`) and re-run only when that changes. Each is also saved as a committed file (`data/<creator>/profiles/`), which `segment` restores into a rebuilt database while the video's segments are unchanged ([D17](DECISIONS.md#d17-profiles-are-kept-as-committed-files)). Cost in the first trial: about $0.19 per video.

### 4. Index

Every transcript segment becomes a **contextual chunk**: the segment text plus a header naming its video, publish date, section (title and summary) and any sponsor read or aside it overlaps. A chunk then makes sense on its own when retrieved. Each video's profile text and the questions it answers are indexed alongside.

- **Keyword search:** SQLite FTS5 (BM25, stemming).
- **Vector search:** chunks embedded (OpenAI `text-embedding-3-small` by default) and searched by cosine similarity (SQLite, exact search with numpy). An embedding is reused while its chunk's text and the embedder are unchanged.

If embeddings are unavailable, keyword search is still built and the run warns.

**Tried and dropped: overlapping chunks.** Most transcripts are auto captions without punctuation, so 59% of segment boundaries fall mid-sentence. Giving each search chunk 15 or 40 words from its neighbours made no difference: with the same saved queries, 89% of the passages full mode cited were in the top 60 candidates either way, and slightly fewer reached the top 20 (102 and 97 against 106). Section headers already carry the context a cut loses, and kept passages expand to their section. Where hybrid loses material, it's at the rerank step.

### 5. Answer

Set by `[retrieval] mode` in `askthe.toml`.

**`hybrid` (default)**
1. **Plan.** A fast model (Claude Haiku) turns the question into 3 to 6 search queries (rephrasings, synonyms, the informal words he would say) and the names involved; names are expanded with glossary aliases and caption misspellings. It also says whether the question needs a catalogue-wide sweep.
2. **Search and fuse.** Every query runs on keyword and vector search; the ranked lists are combined with **reciprocal rank fusion**, with a boost for passages from videos whose profile matches. The top 60 (100 for sweeps) become candidates.
3. **Rerank.** The fast model scores each candidate 0 to 3 for this question; passages scoring 2 or more are kept.
4. **Assemble.** Each kept passage expands to its section when the section is short, otherwise to its neighbours, within a word budget (`context_words`, default 12,000). Videos are shown with their sections listed and skipped stretches marked, so the model knows the transcript is partial.
5. **Answer, verify, log** as below.

If vector search fails, retrieval continues on keywords alone and the answer carries a warning. With `require_profiles` on (the default), only profiled videos are searched (D22).

**`full`**: whole transcripts, every video if the catalogue fits `full_budget_words`, otherwise the best-matching videos. Kept as an option and an occasional sanity check; evals measure hybrid against the test set instead (D21).

**Answer, verify, log (both modes).** Each video is shown with its description (his words, links collapsed) and its transcript. The model answers this question from what it was given, following the product rules and D19, and cites every statement with a video, a segment (or the description) and an exact quote. Code checks every quote appears in the segment it cites; one retry is allowed, and anything still failing is removed and reported. The question, answer, coverage, cited segments and retrieval mode are logged.

**First real comparison** (22 videos, keyword-only because embeddings were not yet reachable): hybrid read 715 to 2,104 words per question instead of 63,000, gave the same conclusions as full context, and cost about $0.06 to $0.10 per question regardless of catalogue size. Full context costs about $0.60 per question when the cache is cold.

**With vector search** (same 22 videos, 3 profiled): embedding all 421 chunks took 90k tokens, about $0.002. On the same three questions vector search changed about a third of the candidates but no conclusion: keyword search alone already found every passage full mode cited, near the top. Hybrid cost $0.01 to $0.08 per question against $0.03 to $0.62 for full mode, and read 0 to 2,745 words against 63,000. Whether vectors help with questions that don't name the product is for the M4 test set to show.

### The web page

`askthe serve` runs the ask pages for every creator in `creators/` (or `askthe serve <creator>` for one): `askthe/app/`, FastAPI and one plain HTML/JS page (see [UI_PLAN](UI_PLAN.md)). `/` is the catalog of creators, `/<slug>` a creator's page (who they are, from the creator config, `channel.json` and `bio.json`, then the ask box), `/a/<id>` an answer. The API is under `/api/creators/<slug>/…`; answer lookups check the answer's `creator_id` against the creators being served. Slugs can't be `static`, `api` or `a`. A question is answered in a worker thread and streamed to the page as newline-delimited JSON: searching, the videos being read, the answer text as it's written, then the verified answer. Citations stay grey until code has verified them; failed ones are removed. Every answer is saved as a snapshot with its own link. A fan's list of questions lives in their browser, one list per creator; "new video since you asked" is a keyword search over videos published after the answer, with no model call.

## Swappable components

Each of these is an interface in the engine core, with implementations as adapters. The config file picks which adapter is used.

| Interface | Job | First implementation | Likely later swaps |
| --- | --- | --- | --- |
| `CatalogSource` | List a creator's videos and their metadata | yt-dlp | YouTube Data API; creator-supplied export |
| `TranscriptSource` | Get the transcript text for a video | youtube-transcript-api; or `files` (`.vtt`, `.srt`, `.txt`) | yt-dlp subtitles; Whisper on audio; a transcript service |
| `CommentSource` | Get viewers' comments on a video, for collecting real fan questions | yt-dlp (top comments, no replies, no authors) | YouTube Data API |
| `ProfileArchive` | Keep video profiles outside the database (D17) | files in `data/<creator>/profiles/` | |
| `KnowledgeStore` | Save and query videos, segments, profiles, entities, answer logs | SQLite | Postgres |
| `SearchIndex` | Find relevant segments and claims for a query | SQLite full-text search (FTS5) | Hybrid with vectors; a dedicated search service |
| `Embedder` | Turn text into vectors | OpenAI `text-embedding-3-small` | Voyage; a local model (BGE) |
| `VectorIndex` | Nearest-neighbour search over embeddings | SQLite + numpy (exact) | sqlite-vec, pgvector, a vector database |
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
  pipeline/        fetch, segment, understand, index, ask
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
