# CLAUDE.md

Guidance for coding agents working in this repo. Read [README](README.md) first, then [ARCHITECTURE](docs/ARCHITECTURE.md) and [DATA_MODEL](docs/DATA_MODEL.md) before changing code.

## What this is

AskThe turns a creator's videos into a knowledge base of their verdicts, and answers fan questions with the creator's own answer plus timestamped links. Current phase: **Phase 1, private prototype**, for The Iron Snail. See [PROTOTYPE_SPEC](docs/PROTOTYPE_SPEC.md).

## Product rules (never break these)

1. **Grounded or silent.** Answers use only retrieved evidence from the creator's content. If there's no evidence, the answer says it isn't covered. Never let the model fill gaps from general knowledge.
2. **Every answer cites.** Each claim in an answer links to a video at a timestamp. Citations are verified in code against stored segments, never trusted from model output.
3. **Newest verdict wins.** Order evidence by publish date; say when the creator changed their mind and cite both.
4. **Third person, no imitation.** Answers describe what the creator said ("The Iron Snail recommends…"). Never write in the creator's voice or style.
5. **Quotes are verbatim.** An extracted quote must appear in the segment it cites.

## Engineering rules

- **Creator-agnostic engine.** No creator names, niches or categories hard-coded in `askthe/`. They belong in `creators/<slug>.yaml`.
- **Ports and adapters.** External dependencies (YouTube, database, search, embeddings, LLM) are reached only through interfaces in `askthe/core/`. Implementations live in `askthe/adapters/`. Only `askthe/wiring.py` constructs adapters.
- **Core has no I/O.** `askthe/core/` holds domain models and pure logic; it never imports an adapter, SDK or database driver.
- **Raw data is the source of truth.** Never modify files in `data/<creator>/raw/`. Every derived artefact must be rebuildable from it.
- **Version extraction.** Anything that changes extraction output (prompt, schema, model) bumps the extractor version, which is stored on every claim.
- **Fakes for tests.** Each interface has an in-memory fake. Unit tests use fakes; no network or API keys in unit tests.
- **Model names in config,** never in code.
- **Evaluate before claiming improvement.** Changes to extraction, retrieval or answering are checked with `askthe eval` (see [EVALUATION](docs/EVALUATION.md)); include before and after scores in the commit or PR description.

## Docs

- Record significant decisions in [DECISIONS](docs/DECISIONS.md) as a new entry.
- Keep [ROADMAP](docs/ROADMAP.md) milestone status current.
- Update [DATA_MODEL](docs/DATA_MODEL.md) when the schema changes.

## Environment notes

- Fetching from YouTube needs network access to YouTube. If it's blocked, run `askthe fetch` locally and copy `data/<creator>/raw/`; all later stages run offline.
- `data/` is git-ignored. Secrets (API keys) come from environment variables, never committed.
