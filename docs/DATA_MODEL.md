# Data model

> **Draft.** This will be checked against a real Iron Snail transcript before we build on it.

## Layers

The data comes in three layers. Each is derived from the one before and can be rebuilt from it.

1. **Raw:** exactly what was fetched. Never edited. Source of truth.
2. **Segments:** cleaned, timestamped chunks of transcript. Still the creator's words.
3. **Knowledge:** extracted claims, products and summaries. An index over the segments, versioned, always pointing back to them.

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
| `video_type` | `review`, `comparison`, `buying_guide`, `long_term_review`, `how_to`, `other` |
| `categories` | Which of the creator's categories the video covers |
| `summary` | Short extracted summary |

### Segment

| Field | Notes |
| --- | --- |
| `id`, `video_id` | |
| `start_s`, `end_s` | Seconds from video start |
| `text` | Cleaned transcript text |
| `chapter` | Chapter title, if any |

### Product

| Field | Notes |
| --- | --- |
| `id`, `creator_id` | Products are per creator |
| `canonical_name`, `brand`, `model` | "Red Wing Iron Ranger 8111" |
| `category` | One of the creator's categories |
| `aliases` | Names used in videos and transcripts ("Iron Rangers", "the Red Wings") |
| `affiliate_url` | Placeholder for later |

### Claim

The core unit of knowledge. One thing the creator said, tied to where they said it.

| Field | Notes |
| --- | --- |
| `id`, `video_id` | |
| `segment_ids`, `start_s`, `end_s` | Where it was said |
| `quote` | The creator's words, verbatim from the segment, so it can be checked |
| `kind` | See claim kinds below |
| `product_ids` | Zero, one or several (several for comparisons) |
| `brand` | For brand-level opinions |
| `statement` | One-sentence plain-language summary of the claim |
| `stance` | For verdicts: `recommend`, `positive`, `mixed`, `negative`, `avoid`, `neutral` |
| `pros`, `cons` | Lists of short phrases |
| `good_for`, `bad_for` | Uses or conditions ("wet winters", "daily wear") |
| `price` | `{amount, currency, as_said}`; `as_said` keeps the original wording ("around three hundred bucks") |
| `context` | Conditions the claim depends on ("after two years of wear", "if you size down") |
| `attributes` | Open key-value details: `{fit: "runs half a size large", made_in: "Portugal"}` |
| `compared_with` | For comparisons: other product IDs, the criterion, and which won |
| `confidence` | How sure the extractor is (low for garbled auto captions) |
| `extractor_version`, `model` | What produced this claim |

### Claim kinds

| Kind | Example |
| --- | --- |
| `verdict` | "These are the best boots under $300." |
| `comparison` | "The Iron Ranger is warmer than the Blacksmith." |
| `durability` | "After two years the sole separated." |
| `fit_sizing` | "Size down half a size." |
| `advice` | "Don't buy raw denim for your first pair." |
| `technique` | "Here's how I break in leather boots." |
| `brand_opinion` | "Brand X has gone downhill since 2022." |
| `buying_principle` | "Pay for the leather, not the logo." |
| `sponsorship` | "This video is sponsored by…" (shown in answers when relevant) |
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

## Opinions over time

There's no stored "current verdict". It's computed:

- A product's **timeline** is its claims ordered by video publish date.
- The **current view** is the latest verdict-type claim. Long-term reviews outweigh first impressions from around the same time.
- A **change of mind** is a later claim whose stance differs meaningfully from an earlier one. Answers say what changed and cite both.

Computing this rather than storing it means re-extraction or newly added videos update it automatically.

## Keeping the schema from being too rigid

- **Nothing is lost:** raw files and segments are kept and searchable, whatever the schema misses.
- **Claims point to their context:** answers read the transcript around each claim, not just the claim.
- **Open slots:** `attributes`, `context` and the `other` kind catch what the fixed fields don't.
- **Re-runs are cheap:** extraction is versioned and re-runs from saved segments.
- **We measure gaps:** a coverage report flags long stretches of transcript that produced no claims, and evaluation flags questions answerable only from raw text search. Both feed schema changes. See [EVALUATION](EVALUATION.md).
