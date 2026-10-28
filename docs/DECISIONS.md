# Decisions

A short log of decisions: what we chose, why, and what we didn't choose. Newest at the bottom. To revisit a decision, add a new entry that supersedes it rather than editing the old one.

---

### D1. Knowledge expert, not a personality clone
*2026-10-28*

**Chose:** an assistant that reports the creator's verdicts in the third person, with sources.
**Why:** fans want the creator's answers, not an imitation. Clone products exist and have been badly received; accuracy and sources build trust.
**Rejected:** voice or personality imitation (may revisit as an optional layer much later, only with the creator's agreement).

### D2. "Ask The ___" as a template
*2026-10-28*

**Chose:** one creator-agnostic engine; each creator is an instance ("Ask The Iron Snail") defined by a config file.
**Why:** the business depends on onboarding the next creator in days, not weeks.
**Rejected:** building a one-off for The Iron Snail and generalising later.

### D3. The Iron Snail first, one creator at a time
*2026-10-28*

**Chose:** The Iron Snail's YouTube videos for the prototype. One creator at a time.
**Why:** buyer's-guide content with clear verdicts is an ideal first case; gear questions carry buying intent.
**Note:** the prototype is private, unmonetised and for testing only. Nothing goes public without the creator's agreement.

### D4. Transcripts are the source of truth; extraction is a rebuildable index
*2026-10-28*

**Chose:** keep raw transcripts and segments forever; treat extracted claims as a versioned index pointing back to them; answers read the transcript around each claim.
**Why:** a rigid extraction schema would lose context we haven't thought of yet. This way, nothing is lost and schema changes are a cheap re-run.
**Rejected:** extract-then-discard pipelines; answering from summaries alone.

### D5. Swappable components behind interfaces
*2026-10-28*

**Chose:** ports and adapters. Sources, storage, search, embeddings and the LLM each sit behind an interface; config picks the implementation.
**Why:** we expect to change how content is loaded, which database we use and how search works. Each change should be one adapter, not a rewrite.

### D6. Python, SQLite with full-text search, no vectors at first
*2026-10-28*

**Chose:** Python; SQLite with FTS5; structured lookup over claims plus text search over segments.
**Why:** about 50 videos fit easily; zero setup; fastest path to the Phase 1 gate.
**Rejected for now:** a vector database. Added behind the search interface only if evaluation shows text search missing questions.

### D7. Claude for extraction and answering; model chosen in config
*2026-10-28*

**Chose:** the Anthropic API for structured extraction and grounded answers, with the model name in config.
**Why:** strong structured output and instruction following; config keeps it swappable.

### D8. Citations are checked in code
*2026-10-28*

**Chose:** the model cites evidence IDs from what it was given; code maps them to real videos and timestamps and rejects anything it can't verify.
**Why:** a wrong link or invented quote damages the creator's name and ours. "Grounded or silent" has to be enforced, not requested.
