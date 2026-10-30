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

### D16. Hybrid retrieval by default
*2026-10-29*

**Chose:** answers read retrieved sections, not whole transcripts: contextual chunks indexed for keyword (BM25) and vector search, queries planned and expanded by a fast model, lists fused with reciprocal rank fusion, candidates reranked by a fast model, and kept passages expanded to their sections within a word budget. Embeddings from OpenAI (`text-embedding-3-small`), behind the `Embedder` interface. Whole-transcript reading stays as `mode = "full"`.
**Why:** reading every transcript doesn't scale (his full channel is about 800k tokens; multiple creators far more), costs about $0.60 per question once the cache is cold, and dilutes attention. In the first comparison hybrid read 2 to 3 percent as much text and gave the same conclusions.
**Measure:** hybrid is checked against full mode on the test set (EVALUATION), including recall of the videos and segments full mode cites.

### D17. Profiles are kept as committed files
*2026-10-29*

**Chose:** each video profile is saved, with the entities it names, to `data/<creator>/profiles/<video_id>.json` and committed. `segment` restores saved profiles into the rebuilt database when the segments they were made from are unchanged (checked by a fingerprint of the segment texts). Stale ones are reported, and `understand` makes new ones.
**Why:** a profile costs about $0.20 of model time and comes out slightly differently each run, so it is expensive and not exactly reproducible. With profiles only in the git-ignored database, a fresh environment lost them and paid again. Files also make profiles reviewable in diffs.
**Still rebuildable:** profiles remain derived. Deleting the folder and running `understand` rebuilds them; raw files stay the only source of truth.

### D18. Comments are used only for the test set, for now
*2026-10-29*

**Chose:** viewers' comments are collected (`askthe comments`, `askthe questions`) only to find real fan questions for the test set. They are not indexed, retrieved or shown to the answering model.
**Why:** fans' views are not his (rules 1 and 7), and likes measure agreement, not truth: a well-liked comment contradicting him is a bigger risk, not a smaller one. The useful uses need more design than the prototype warrants yet.
**Later options:** his own comments and replies as citable content (fetching replies only for the most-liked threads, to limit requests); nicknames mined from comments, weighted by likes, as glossary suggestions; demand and coverage gaps for a creator dashboard. Each would be checked with `askthe eval` before being kept.

### D19. How answers read, from the first review
*2026-10-29*

**Chose**, after Liam reviewed the baseline answers:
- **His rules may be applied** to the fan's details ("two sizes up" from their size), as long as it's clearly his rule applied.
- **Mixed views get a general lean** ("mostly yes, but…") followed by his dated opinions; answers needn't force black and white.
- **Not covered is said briefly** ("hasn't covered X in the videos available here"), with at most one cited line on the closest thing he did cover. Answers never mention transcripts, excerpts or their inputs, and never ask the fan for a video.
- **Length follows the question:** several products earn a part each; it stays readable.
- **Descriptions are his words.** Each video's description is shown with links collapsed and is citable (segment -1), its quotes verified in code like any other; promo codes and sponsor mentions in it are advertising. Section summaries written by the profiler are for finding things only and are never cited.
**Why:** the baseline's only two failures (q18, q19) were answers that talked about missing transcripts; one answer stated a profile summary as fact; descriptions hold real opinions ("not featured in video but amazing pieces").

### D20. Sonnet 5.5 answers questions
*2026-10-29*

**Chose:** Claude Sonnet 5.5 (effort `high`) for answering, set in `askthe.toml`. Profiles stay on Opus 5.5; planning and reranking stay on Haiku 5.5. Supersedes D13 for answering.
**Why:** compared on the 23-question set in hybrid mode (answering model only): Opus high $0.093 a question, Opus medium $0.072, Sonnet $0.041, Haiku $0.007. All passed the automated checks, and reading the answers showed no quality worth Opus's price. Haiku was accurate but thin; Sonnet keeps structure and depth at under half Opus's cost, and is the fastest (about 14 s). With the D19 rules and the personal-life rule, Sonnet's run passed every check with no personal-life slips, for $0.92 for all 23.
**Watch:** Sonnet dropped part of a hedge once (q05: "still might be", without "but probably not") and labels many complete answers "partial". Both are prompt fixes, checked with `askthe eval`.

### D21. Evals run hybrid only; the test set is the retrieval reference
*2026-10-30*

**Chose:** `askthe eval` runs hybrid mode, the one fans use, by default. Retrieval is checked against each question's expected source videos (`sources`), reported as the share of them read. Full mode stays in the code as an option (`--mode full`), not part of every run.
**Why:** full mode was only ever a reference for hybrid, and its first question costs about $1.15 to load the catalogue. The test set already names the videos that hold each answer, which checks retrieval directly and stays meaningful as the catalogue outgrows full mode. Supersedes the measurement note in D16.
**Trade-off:** expected sources count videos, not passages, so the expectations must name every video an answer should draw on (q05 now includes the 2021 1907 review).

### D22. Answers use only profiled videos
*2026-10-30*

**Chose:** with `[retrieval] require_profiles = true` (the default in `askthe.toml`), answers read only videos that have a profile. A newly fetched video is used once `askthe understand` has profiled it; `serve` warns how many are waiting, and the page's video count and "new video since you asked" count only usable videos.
**Why:** without a profile, sponsor reads and asides aren't marked, so a paid read could be presented as his opinion (rule 6) and personal remarks aren't flagged (rule 8). Transcripts arrive in batches ahead of profiling, and a missing profile shouldn't quietly weaken answers.

### D23. The creator page is about the creator, from their own words
*2026-10-30*

**Chose:** the creator page leads with a bio of who they are as a whole, not a copy of a platform's "About": a summary, a dated journey and their ventures (own brands, products, collaborations). `askthe bio` writes it once per creator with one model call over a catalogue of their profiled videos and the passages where they talk about their own work; every item must cite quotes, which code verifies against the cited video, and items touching personal life are dropped (rule 8). Links are platform-neutral (YouTube, store, later Instagram or Substack). The YouTube channel info supplies the avatar.
**Why:** fans come for the person and their judgement, across everything they make; content from other platforms may follow. Grounding the bio in quotes keeps it as trustworthy as the answers.
**Watch:** the catalogue is only the ingested videos, so the bio avoids "first" and "started with" claims unless the creator says so; the first draft got the brand's order wrong (it named the Mammoth as first, though the Prologue came a year earlier) until the passages for each product were searched first.
