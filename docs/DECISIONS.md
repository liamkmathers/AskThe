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

### D9. Understand the video before extracting from it; entities, not just products
*2026-10-28*

**Chose:** two-pass extraction. Pass A writes a video profile (purpose, type, thesis, topics, entities, segment roles, the questions it answers, how fans would use it). Pass B extracts claims with that profile as context. Knowledge attaches to typed entities (product, component, material, brand, person, concept), not only products. Sponsor segments are marked, and claims from them are never treated as verdicts.
**Why:** tested against a real transcript (an explainer on Vibram soles). Most of its knowledge was explanation and history about a sole, a rubber compound and a brand, not a verdict on a product, and it contained a sponsor skit full of product claims. A product-only, sentence-by-sentence extractor would have missed the point of the video and risked presenting sponsored claims as the creator's opinion.
**Rejected:** a single pass with a fixed product-verdict schema.

### D10. Verdicts are per aspect, per version, and attributed
*2026-10-28*

**Chose:** each verdict records the aspect judged (value, quality, fit…), the product version when one is named (vintage vs modern), whose view it is (`held_by`), and the creator's own certainty. Videos can correct themselves, and later in-video claims supersede earlier ones. Prices carry a type (retail, sale, used). Unidentifiable names stay unresolved rather than guessed. A per-creator glossary corrects caption errors. Nothing about the personal life of the creator, family or friends is extracted.
**Why:** tested against two more transcripts. A brand verdict built on vintage-vs-modern comparisons, with reported opinions the creator disagreed with, heavy hedging and an editor's correction. A value ranking where one product was "great quality, odd fit", the ranking was revised at the end, prices were sale or used, some products were shown but never named, and caption errors mangled most brand names. A single stance per product would have produced confident, wrong answers.
**Rejected:** one stance per product; treating every opinion voiced in a video as the creator's.
