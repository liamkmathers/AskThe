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

**Chose:** the model cites evidence IDs from what it was given; code maps them to real videos and segments, checks each quote appears there, and rejects anything it can't verify.
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

### D11. His taste is the product
*2026-10-28*

**Chose:** personal taste and judgement are treated as the most valuable knowledge in the system. A `preference` claim kind captures taste with or without a product; `he_wears_it` records what he uses himself; `personal_taste` is a basis that never lowers a claim's weight; extraction keeps every opinion however brief; answers lead with his view. Evaluation measures opinion recall separately.
**Why:** objective facts about products are easy to find online. A creator's opinion, often said once in passing in one video, is not. That's what fans come for.
**Rejected:** treating taste as weaker evidence than testing, or as a disclaimer on an answer.

### D12. No timestamps
*2026-10-28*

**Chose:** nothing in the system depends on timestamps. Transcripts are stored as plain text; segments are ordered chunks of text; claims cite segments and quote the creator's words; answers link to the video, not a moment in it. Citations are verified by checking that each quote appears in the cited segment.
**Why:** relying on timing makes the system fragile. Many transcript sources (pasted text, simple services, some exports) have none, and the stage that fetches timed captions is the one YouTube blocks from cloud servers. Without timing, any source of a video's words works.
**Trade-off:** fans land at the start of the video rather than the exact moment; the quote makes the passage recognisable. This changes the concept brief's "link to the exact moment" and its acceptance test, which now requires quoted, linked sources instead of timestamp links. Jump-to-moment links could return later as an optional extra, never a requirement.

### D13. Extraction on Claude Opus 5.5, with the whole video as cached context
*2026-10-28*

**Chose:** Claude Opus 5.5 for all three tasks (understand, extract, answer) at effort `high`, set per task in `askthe.toml`. Pass B runs over windows of about 8 segments, but every call carries the whole numbered transcript and the profile, marked for prompt caching, so each window is read in the context of the full video and the repeated input is cheap. Structured outputs (pydantic schemas) shape the responses; code then checks every quote against its segment and drops claims that fail. Server-side refusal fallbacks are on, and the model that actually answered is recorded on each claim.
**Why:** extraction is judgement-heavy (attribution, hedging, sponsorship, taste) and errors become misquotes. Whole-video context was the lesson of the transcript tests (D9). Windows keep each response small enough to finish reliably.
**Revisit:** a cheaper model or lower effort for some tasks once the evaluation shows where quality holds.

### D14. His own products are his opinion, not sponsorship
*2026-10-28*

**Chose:** what the creator says about his own products or brand is extracted as ordinary claims (his opinion), marked with the attribute `own_product = "yes"`, never as sponsorship.
**Why:** it's his genuine view and more information for fans. The attribute keeps it identifiable if answers ever need to mention it.

### D15. Reason at question time, not extraction time
*2026-10-29*

**Chose:** no opinions, verdicts or claims are extracted in advance. Each video gets a profile that describes it (metadata, sections, entities, precisely located sponsor reads and asides, the questions it answers). At question time the relevant full transcripts, with that metadata, are given to the model, which reasons about this specific question and cites exact quotes that code verifies. Supersedes the claim extraction of D9, D10, D11 and D13; their rules (his taste first, attribution, hedging, sponsorship, versions, corrections) now apply when answering.
**Why:** what matters in a video depends on the question. A trial of claim extraction on real videos cost about $1 per video, produced around 90 field-heavy claims each, and lost meaning: sponsor marking per segment flagged genuine opinions as sponsored. Reasoning over the transcript at question time kept the nuance (in-video re-rankings, hedges, others' views) in every test answer, every quote verified, at $0.03 to $0.06 per cached question. The 50-video prototype fits in the model's context outright.
**Rejected:** a fixed per-claim schema. A structured product list may return later for specific features (browsing, dashboard), derived from answers or added if evaluation shows a need.
