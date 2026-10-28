# Data model

> **Draft, revised once.** First checked against a real Iron Snail transcript ("Why The Same Brand Is On The Bottom Of Every Boot", an explainer about Vibram). That test led to entities beyond products, video profiles, segment roles, and the `explanation`, `history` and `mention` claim kinds. Expect more revisions as more videos are tested.

## Layers

The data comes in three layers. Each is derived from the one before and can be rebuilt from it.

1. **Raw:** exactly what was fetched. Never edited. Source of truth.
2. **Segments:** cleaned, timestamped chunks of transcript. Still the creator's words.
3. **Knowledge:** video profiles, extracted claims and entities. An index over the segments, versioned, always pointing back to them.

Answers are built from layer 3 *and* the layer 2 text around each claim, so the nuance the extraction missed is still available.

## Entities

### Creator

| Field | Notes |
| --- | --- |
| `id`, `slug` | `iron-snail` |
| `display_name`, `instance_name` | "The Iron Snail", "Ask The Iron Snail" |
| `channel_url`, `niche`, `categories` | From the creator config |

### Video

| Field | Notes |
| --- | --- |
| `id`, `creator_id`, `platform_id` | `platform_id` is the YouTube ID |
| `title`, `description`, `published_at`, `duration_s` | From metadata |
| `chapters` | List of `{title, start_s}`, if present |
| `tags`, `view_count`, `thumbnail_url` | From metadata |
| `transcript_kind` | `manual` or `auto`; auto captions are less reliable on brand names |

### Video profile

What the video is, as a whole. Written by the understanding pass before any claims are extracted, and given to the claim extractor as context.

| Field | Notes |
| --- | --- |
| `video_id` | |
| `purpose` | What the video is for, in a sentence ("Explain why Vibram soles are on so many good boots, through the history and design of the Carrarmato sole.") |
| `video_type` | `review`, `comparison`, `buying_guide`, `long_term_review`, `explainer`, `how_to`, `other` |
| `thesis` | The argument the creator is making |
| `key_takeaways` | A few sentences a fan should leave with |
| `topics` | Plain-language topics ("outsole design", "grip vs traction", "Vibram history") |
| `entity_ids` | Entities the video covers, with names corrected from caption errors |
| `categories` | Which of the creator's categories it touches |
| `answers_questions` | Fan questions this video is a good source for |
| `uses` | `buying_decision`, `care_maintenance`, `understanding`, `background_history`, `style` |
| `related_videos` | Other videos it refers to ("Ventile next video"), when identifiable |
| `extractor_version`, `model` | |

### Segment

| Field | Notes |
| --- | --- |
| `id`, `video_id` | |
| `start_s`, `end_s` | Seconds from video start |
| `text` | Cleaned transcript text |
| `chapter` | Chapter title, if any |
| `role` | Set by the understanding pass: `main`, `intro`, `sponsor`, `aside` (skits, jokes, tangents), `outro` |

### Entity

Anything a fan might ask about by name. Products are the most common, but not the only kind.

| Field | Notes |
| --- | --- |
| `id`, `creator_id` | Entities are per creator |
| `type` | `product`, `component` (a sole, a zipper, a construction method), `material` (Horween Chromexcel, merino), `brand`, `person`, `concept` (grip, traction, goodyear welt) |
| `canonical_name` | "Vibram Carrarmato outsole", "Red Wing Iron Ranger 8111" |
| `brand`, `model`, `category` | Where they apply |
| `aliases` | Names used in videos and caption misspellings ("Iron Rangers", "Carramato") |
| `related_entity_ids` | e.g. a boot and the sole it uses; a compound and its brand |
| `affiliate_url` | Products only; placeholder for later |

### Claim

The core unit of knowledge. One thing the creator said, tied to where they said it.

| Field | Notes |
| --- | --- |
| `id`, `video_id` | |
| `segment_ids`, `start_s`, `end_s` | Where it was said |
| `quote` | The creator's words, verbatim from the segment, so it can be checked |
| `kind` | See claim kinds below |
| `entity_ids` | Zero, one or several (several for comparisons) |
| `statement` | One-sentence plain-language summary, attributed to the creator ("He says…") |
| `stance` | For verdicts and opinions: `recommend`, `positive`, `mixed`, `negative`, `avoid`, `neutral` |
| `basis` | What the opinion rests on: `own_testing`, `long_term_wear`, `research`, `interview` (e.g. what Vibram's designers told him), `hearsay` |
| `pros`, `cons` | Lists of short phrases |
| `good_for`, `bad_for` | Uses or conditions ("wet winters", "daily wear") |
| `price` | `{amount, currency, as_said}`; `as_said` keeps the original wording ("around three hundred bucks") |
| `context` | Conditions the claim depends on ("after two years of wear", "if you size down") |
| `attributes` | Open key-value details: `{fit: "runs half a size large", made_in: "Portugal"}` |
| `compared_with` | For comparisons: other entity IDs, the criterion, and which won |
| `use` | How a fan would use it: same values as the profile's `uses` |
| `sponsored` | True for anything said in a sponsor segment or about a sponsor |
| `confidence` | How sure the extractor is (low for garbled auto captions) |
| `extractor_version`, `model` | What produced this claim |

### Claim kinds

| Kind | Example |
| --- | --- |
| `verdict` | "These are the best boots under $300." |
| `comparison` | "The Iron Ranger is warmer than the Blacksmith." |
| `durability` | "After two years the sole separated." |
| `fit_sizing` | "Size down half a size." |
| `explanation` | "Grip is friction on smooth surfaces; traction is lugs biting into the ground." |
| `history` | "The Carrarmato followed a 1935 climbing accident." |
| `advice` | "Don't buy raw denim for your first pair." |
| `technique` | "Here's how I break in leather boots." |
| `brand_opinion` | "Nobody is in Vibram's league for outsoles." |
| `buying_principle` | "Pay for the leather, not the logo." |
| `mention` | "Vibram redesigned the Air Force 1 outsole." (named, no verdict) |
| `sponsorship` | A sponsor read, recorded so it's never mistaken for a verdict |
| `other` | Anything worth keeping that fits none of the above |

The list is a starting point. New kinds and new standard attributes are added when they keep showing up in `other` and in `attributes`.

### Answer log

| Field | Notes |
| --- | --- |
| `id`, `creator_id`, `asked_at` | |
| `question`, `answer` | |
| `covered` | `full`, `partial`, `none` |
| `cited_claim_ids`, `cited_segment_ids` | |
| `pipeline_versions` | Extractor, prompt and model used |

## Attribution and sponsorship

- **Everything is the creator's account.** Facts, history and explanations are stored and answered as what the creator said ("He says the Carrarmato was named after the Italian for tank"), not as verified truth.
- **Sponsored is never a verdict.** Claims from sponsor segments carry `sponsored: true`. Answers never present them as an independent recommendation, and say so if they come up.

## Opinions over time

There's no stored "current verdict". It's computed:

- An entity's **timeline** is its claims ordered by video publish date.
- The **current view** is the latest verdict or opinion claim. Long-term reviews and own testing outweigh first impressions and hearsay from around the same time.
- A **change of mind** is a later claim whose stance differs meaningfully from an earlier one. Answers say what changed and cite both.

Computing this rather than storing it means re-extraction or newly added videos update it automatically.

## Keeping the schema from being too rigid

- **Understand first:** the video profile gives the extractor the purpose and argument of the video before it pulls out details.
- **Nothing is lost:** raw files and segments are kept and searchable, whatever the schema misses.
- **Claims point to their context:** answers read the transcript around each claim and the video's profile, not just the claim.
- **Open slots:** `attributes`, `context` and the `other` kind catch what the fixed fields don't.
- **Re-runs are cheap:** extraction is versioned and re-runs from saved segments.
- **We measure gaps:** a coverage report flags long stretches of main-content transcript that produced no claims, and evaluation flags questions answerable only from raw text search. Both feed schema changes. See [EVALUATION](EVALUATION.md).
