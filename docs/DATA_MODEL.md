# Data model

> **Draft, tested against three real Iron Snail transcripts:**
>
> 1. "Why The Same Brand Is On The Bottom Of Every Boot", an explainer about Vibram. It led to typed entities, video profiles, segment roles, and the `explanation`, `history` and `mention` claim kinds.
> 2. "Is Patagonia Really THAT Good?", a brand verdict built on vintage-vs-modern comparisons. It led to product versions, `held_by`, `certainty`, in-video corrections, video outlines, the glossary and the personal-life rule.
> 3. "The Highest Quality, Lowest Price Clothing, Ranked", a value ranking of about 20 products across four categories. It led to verdict aspects, rankings, price types and unresolved entities.
>
> Expect smaller revisions as more videos are processed.
>
> **Since [D15](DECISIONS.md#d15-reason-at-question-time-not-extraction-time):** opinions are no longer extracted in advance. The pipeline produces **videos, segments, profiles and entities**; the model reasons over full transcripts at question time. The `Claim`, `ProductVersion` and claim-kind sections below describe *what answers must handle* (aspects, versions, attribution, hedging, rankings, sponsorship), not records the pipeline writes. The `Claim` record type remains in the code, unused, in case a structured product list is added later.

## Layers

The data comes in three layers. Each is derived from the one before and can be rebuilt from it.

1. **Raw:** exactly what was fetched. Never edited. Source of truth.
2. **Segments:** cleaned, ordered chunks of transcript. Still the creator's words.
3. **Knowledge:** video profiles, extracted claims and entities. An index over the segments, versioned, always pointing back to them.

Answers are built from layer 3 *and* the layer 2 text around each claim, so the nuance the extraction missed is still available.

## Records

### Creator

| Field | Notes |
| --- | --- |
| `id`, `slug` | `iron-snail` |
| `display_name`, `instance_name` | "The Iron Snail", "Ask The Iron Snail" |
| `channel_url`, `niche`, `categories` | From the creator config |
| `glossary` | Known names and their common caption errors, from the creator config (see below) |
| `starter_questions` | Example questions shown on the ask page |
| `own_uploads` | `true` (default) when the videos are on the creator's own channel. `false` when they're talks and interviews on other people's channels: the descriptions are the uploader's words, so answers neither see nor quote them, and the bio can't cite them |
| `tagline`, `about` | One line and a short paragraph for the creator's page, written in the config (never personal life) |
| `links` | Where the creator is (channel, store, socials), platform-neutral, from the config |
| `bio` | Who they are as a whole: a summary, a dated journey and their ventures (own brands, products, collaborations), each item citing quotes verified against the cited video. Made by `askthe bio` into `data/<creator>/bio.json` (committed). Professional life only |
| `channel` | Name, description, avatar, banner and subscriber count as the platform shows them, fetched by `askthe channel` into `data/<creator>/channel.json` (committed, refreshed by running it again) |

### Video

| Field | Notes |
| --- | --- |
| `id`, `creator_id`, `platform_id` | `platform_id` is the YouTube ID |
| `title`, `description`, `published_at`, `duration_s` | From metadata. The description is also used to identify products named in the video |
| `chapters` | Chapter titles in order, if present |
| `tags`, `view_count`, `thumbnail_url` | From metadata |
| `transcript_kind` | `manual` or `auto`; auto captions are less reliable on names |

### Video profile

What the video is, as a whole. Written by the understanding pass before any claims are extracted, and given to the claim extractor as context.

| Field | Notes |
| --- | --- |
| `video_id` | |
| `purpose` | What the video is for, in a sentence ("Find the best value across denim, chinos, sweatshirts and t-shirts.") |
| `video_type` | `review`, `comparison`, `ranking` (buying guides and "best of" lists), `long_term_review`, `explainer`, `how_to`, `other` |
| `thesis` | The argument the creator is making ("Each price step unlocks tangible quality, up to a point; used is often the real value.") |
| `key_takeaways` | A few sentences a fan should leave with |
| `outline` | Sections: `{title, summary, first_segment, last_segment}`, following his own structure where there is one. Shown to the model at answer time |
| `passages` | Intro, sponsor reads, asides and outro: `{role, first_segment, starts_with, last_segment, ends_with, note}`. Pinned to exact words so they can be marked inside the transcript, even mid-segment. His own products are never a sponsor read |
| `topics` | Plain-language topics ("value for money", "yarn ply", "chinos") |
| `entity_ids` | Entities the video covers |
| `categories` | Which of the creator's categories it touches |
| `answers_questions` | Fan questions this video is a good source for |
| `uses` | `buying_decision`, `care_maintenance`, `understanding`, `background_history`, `style` |
| `corrections` | Places where the video corrects itself (editor's notes, "oops, I just remembered…"): the segment, a note, and the claim it overrides |
| `related_videos` | Other videos it refers to ("part one", "full video on denim coming"), when identifiable |
| `profiler_version`, `model` | What produced this profile |

Saved with the entities it names and a fingerprint of the segments it describes in `data/<creator>/profiles/<video_id>.json` (D17), so rebuilding the database restores it without another model call.

### Raw comments

Viewers' top comments on a video, fetched by `askthe comments` into `data/<creator>/raw/comments/<video_id>.json` and kept like other raw data. Each keeps the comment ID (so it can be linked), text, like count, whether it is a reply or by the creator, and its date. **Authors are not stored.** Used only to collect test-set questions (EVALUATION).

### Segment

| Field | Notes |
| --- | --- |
| `id`, `video_id` | |
| `index` | Position in the video (0, 1, 2…) |
| `text` | Cleaned transcript text |

### Entity

Anything a fan might ask about by name. Products are the most common, but not the only kind.

| Field | Notes |
| --- | --- |
| `id`, `creator_id` | Entities are per creator |
| `type` | `product`, `component` (a sole, a zipper, a construction method), `material` (Horween Chromexcel, merino), `brand`, `service` (a repair programme), `person`, `concept` (grip, traction, loopwheel knitting) |
| `canonical_name` | "Vibram Carrarmato outsole", "Patagonia Retro-X fleece" |
| `brand`, `model`, `category` | Where they apply |
| `aliases` | Names used in videos, including caption misspellings ("Unilo", "Uniclo" → Uniqlo) |
| `resolution` | `resolved`, or `unresolved` when the name can't be pinned down ("the Abercrombie something sweatshirt"). Unresolved entities keep the name as said and are never guessed |
| `related_entity_ids` | e.g. a boot and the sole it uses; a compound and its brand |
| `affiliate_url` | Products only; placeholder for later |

### Product version

Products change over time. A verdict on a 1988 made-in-USA Retro-X says nothing about the current one, and the reverse.

| Field | Notes |
| --- | --- |
| `id`, `entity_id` | The product this is a version of |
| `label` | "Vintage, made in USA, 1988", "Modern" |
| `era` | Year or range, if known |
| `made_in`, `materials`, `notes` | What distinguishes it ("denser pile", "recycled wool with nylon") |

Claims attach to a version when the video names one, and to the product in general otherwise.

### Claim

The core unit of knowledge. One thing said in the video, tied to where it was said.

| Field | Notes |
| --- | --- |
| `id`, `video_id` | |
| `segment_ids` | Where it was said |
| `quote` | Verbatim from the segment, so it can be checked |
| `kind` | See claim kinds below |
| `entity_ids`, `version_ids` | What it's about. Several for comparisons and group claims ("the $3 shirts from Hanes and Gildan all had defects") |
| `statement` | One-sentence plain-language summary, attributed ("He says…") |
| `held_by` | Whose view it is: `creator`, `others` ("people say…", "the internet says…"), `brand` (a company's own claim, e.g. "they say it's loopwheel"), or a named person. Answers never present someone else's view as the creator's |
| `aspect` | What's being judged: `overall`, `value`, `quality`, `durability`, `fit`, `comfort`, `warmth`, `looks`, `ethics`, `performance`. One product can get opposite verdicts on different aspects |
| `stance` | `recommend`, `positive`, `mixed`, `negative`, `avoid`, `neutral` |
| `certainty` | The creator's own hedging: `firm`, `tentative` ("I guess…"), `speculative` ("some of it may be unethically sourced") |
| `basis` | What it rests on: `personal_taste`, `own_testing`, `long_term_wear`, `research`, `interview`, `hearsay`. This records *why* he holds the view, not how much it counts: his taste is the most valuable thing we capture, never a weaker kind of claim |
| `he_wears_it` | True when he says he owns, wears or uses it himself ("I wear it all the time"). One of the strongest signals of his real preferences |
| `pros`, `cons` | Lists of short phrases |
| `good_for`, `bad_for` | Uses or conditions ("wet winters", "hot weather") |
| `price` | `{amount, amount_max, currency, type, as_said}`. `type` is `retail`, `sale`, `used` or `unspecified`; `amount_max` for ranges ("$20–30 on eBay"); `as_said` keeps the original wording. Always shown with the video date |
| `buy_advice` | Where or how to buy, if said: `new`, `used`, `vintage`, `on_sale`, plus notes ("go on eBay") |
| `fit_advice` | Sizing guidance ("go two sizes up", "size down one") |
| `ranking` | For ranking claims: `{list_name, criterion, position, category}` |
| `compared_with` | For comparisons: other entity or version IDs, the aspect, and which won |
| `context` | Conditions the claim depends on ("after one wash", "if you size down") |
| `attributes` | Open key-value details: `{yarn: "two-ply", knit: "loose", neck: "bound"}` |
| `use` | How a fan would use it: same values as the profile's `uses` |
| `sponsored` | True for anything said in a sponsor segment or about a sponsor |
| `superseded_by` | A later claim in the same video that corrects this one |
| `confidence` | How sure the extractor is of its reading (low for garbled captions) |
| `extractor_version`, `model` | What produced this claim |

### Claim kinds

| Kind | Example |
| --- | --- |
| `verdict` | "For $15 the Uniqlo tee is very, very good." |
| `preference` | His personal taste, with or without a product: "I like the dark indigo on Levi's far better than Wrangler's shade", "I'm real big on chinos right now", "I've been loving the quarter-zip look" |
| `comparison` | "Vintage Patagonia rugby sweater beats the modern one by a mile." |
| `ranking` | "Wrangler takes the number one spot for value." |
| `durability` | "After two years the sole separated." |
| `fit_sizing` | "Shrink-to-fit 501s: go two sizes up." |
| `explanation` | "Two-ply yarn is more durable but needs a finer, costlier yarn." |
| `history` | "Chouinard made reusable steel pitons, five times the price." |
| `advice` | "If you only want to spend $50 on chinos, go on eBay." |
| `technique` | "Here's how I break in leather boots." |
| `brand_opinion` | "Muji seems to care more about what goes into its clothing." |
| `buying_principle` | "As you go up in price you unlock tangible things." |
| `mention` | "Vibram redesigned the Air Force 1 outsole." (named, no opinion given) |
| `sponsorship` | A sponsor read, recorded so it's never mistaken for a verdict |
| `other` | Anything worth keeping that fits none of the above |

The list is a starting point. New kinds and new standard attributes are added when they keep showing up in `other` and in `attributes`.

### Answer log

A snapshot of each answer given, so the web page can show it again by its link (`/a/<id>`).

| Field | Notes |
| --- | --- |
| `id`, `creator_id`, `asked_at` | |
| `question`, `answer` | The answer text after verification (failed citations removed) |
| `covered` | `full`, `partial`, `none` |
| `changed_mind` | The answer reports that he changed his mind or hedged over time |
| `sources` | Verified citations: `n`, video, title, published date, URL, quote, segment IDs, `context_before` and `context_after` (about 60 words of his words on each side of the quote, verbatim, taken in code), `in_description`, and `sponsored` (the quote is inside a located sponsor read, set in code) |
| `videos_read` | Videos the answer was based on |
| `parent_id` | The answer this follows up; unused until the page has a chat thread |
| `flagged` | "Something wrong?" notes from fans |
| `cited_claim_ids`, `cited_segment_ids` | |
| `pipeline_versions` | Profiler version, model and retrieval mode used |

Answers live in the database, which is rebuildable from raw data; snapshots are lost if the database is deleted.

## His taste comes first

The creator's opinions are the product. Facts and explanations can be found elsewhere; his taste mostly can't, and it's often said once, in passing ("I like these just because they're brown", "I wear it all the time", "I like my butt in Wrangler pants better").

- **Capture every opinion, however brief.** An offhand remark is a full claim. Extraction never drops an opinion because it's short, informal, or buried in an aside.
- **Taste is not weaker evidence.** `personal_taste` explains why he holds a view; it doesn't lower its weight. Answers present it as his taste ("he personally prefers…"), confidently, not as a disclaimer.
- **What he wears himself** (`he_wears_it`) is recorded wherever he says it, and answers can use it ("he wears the Uniqlo tee all the time").
- **Opinion and fact are kept side by side.** "Camber is heavy and dense" (fact) and "I love it, it feels like an old-school '90s sweatshirt" (taste) are both kept, and the answer leads with the taste.

## Glossary

Auto-captions mangle names badly. One Patagonia video spelled the founder's name five ways (Schwinard, Shwinard, Shinard, Trinard, Sweetard). Each creator config has a glossary of known names with their common mis-hearings, given to the extractor so corrections are consistent:

```yaml
glossary:
  - name: Yvon Chouinard
    type: person
    heard_as: [Ivon Schwinard, Shinard, Shwinard]
  - name: Uniqlo
    type: brand
    heard_as: [Unilo, Uniclo, Unic]
  - name: Vibram Carrarmato
    type: component
    heard_as: [Carramato]
```

The glossary grows as videos are processed: entity resolution proposes new entries, and a person approves them.

## What is not extracted

- **The creator's personal life, and that of family and friends.** Relationships, health, jokes about home life are not knowledge. "He tested it with his partner" can appear in context; facts *about* those people are not stored.
- **Asides and skits**, except where they contain a real claim.

## Attribution, certainty and sponsorship

- **Everything is someone's account.** Facts, history and explanations are stored and answered as what was said ("He says…"), not as verified truth.
- **Whose view:** `held_by` keeps the creator's views separate from views he reports, including views he disagrees with.
- **How sure:** `certainty` carries his hedging into the answer ("he thinks, but isn't sure, that…").
- **Sponsored is never a verdict.** Claims from sponsor segments carry `sponsored: true`, even when they sound personal ("we've both been using it and it's great").
- **Sensitive claims about companies and people** (ethics, controversies) are attributed and hedged exactly as the creator did, never strengthened.

## Opinions over time

There's no stored "current verdict". It's computed per entity (or version) **and aspect**:

- A **timeline** is the claims ordered by video publish date, then by position in the video.
- **Corrections first:** a claim with `superseded_by` is replaced by its correction.
- The **current view** is the latest `creator`-held verdict or preference. Where his own views from around the same time conflict, long-term wear outweighs a first impression, and a firm view outweighs a tentative one. Reported views (`held_by` other than `creator`) never set his current view.
- **Two kinds of change** are kept apart:
  - **He changed his mind:** a later verdict on the same entity or version and aspect differs from an earlier one.
  - **The product changed:** verdicts differ between versions ("the vintage one was better").

  Answers say which it is and cite both.
- **Brand-level questions** ("Is Patagonia worth it?") may have no single stance by design. Answers give the nuance and the specific verdicts rather than forcing one.

Computing this rather than storing it means re-extraction or newly added videos update it automatically.

## Keeping the schema from being too rigid

- **Understand first:** the video profile gives the extractor the purpose, argument and structure of the video before it pulls out details.
- **Nothing is lost:** raw files and segments are kept and searchable, whatever the schema misses.
- **Claims point to their context:** answers read the transcript around each claim and the video's profile, not just the claim.
- **Open slots:** `attributes`, `context` and the `other` kind catch what the fixed fields don't.
- **Re-runs are cheap:** extraction is versioned and re-runs from saved segments.
- **We measure gaps:** a coverage report flags long stretches of main-content transcript that produced no claims, and evaluation flags questions answerable only from raw text search. Both feed schema changes. See [EVALUATION](EVALUATION.md).
