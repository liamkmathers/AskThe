# UI plan (M6), proposal

*2026-10-29. A plan, not built yet; open questions at the end. Researched from existing products (sources at the end), and from the real answers in `eval/runs/`.*

## Direction

**One question, one answer page.** Not a chat thread: the engine answers each question on its own, and a page per answer is easy to save, share and come back to. Mobile first, because fans arrive from a link in his YouTube descriptions.

## What we borrow, and what we avoid

| Product | Take | Avoid |
| --- | --- | --- |
| Perplexity | Citation numbers in place; answer first, then evidence | Source cards pushing the answer down; generic suggested follow-ups |
| NotebookLM | Tapping a citation shows the exact passage; saved answers keep their citations | |
| Google AI Overviews | | Answering so fully that nobody clicks through: "Watch on YouTube" is the main action |
| Consensus | One glanceable signal before the detail | |
| Wirecutter | A decisive pick in plain words; open notes when a pick changes | |
| RTINGS | Dated, visible revisions | |
| YouTube "Ask" | Sources as familiar video cards (thumbnail, title, date) | |
| Delphi-style clones | | Speaking as the creator; a persona instead of evidence |
| Amazon Rufus | Tappable starter questions | The shopping funnel |
| Arc Search | The answer as a page with its own link | Hiding which sources were read |

## The flow

1. **Home:** one input ("Ask about boots, denim…") and three starter questions taken from real fan comments.
2. **Waiting (20–30 s), shown honestly:** "Searching his videos…" → "Reading 4 videos" with their thumbnails → the answer streams in. Citation numbers become tappable only once code has verified the quote.
3. **Answer page:**
   - a verdict card: the answer's own first line ("Mostly yes, with caveats…") and at most one chip: *His view changed*, *Partly covered* or *Not covered*;
   - the reasoning, with [n] citations, nothing collapsed;
   - sources grouped by video, newest first: thumbnail, title, date, then that video's quotes. Sponsored quotes get a grey *Sponsored* tag.
4. **Tapping [n]** opens a sheet: the quote, large ("Listen for: '…'", since there are no timestamps, D12), the video card and a full-width **Watch on YouTube** button.
5. **Not covered** is a calm short card, not an error: "He hasn't covered Gucci jeans in his videos yet", plus the one closest thing he did cover (D19).

## Keeping and coming back

- **No accounts in v1.** Each answer is stored on the server as a snapshot (question, answer, sources, the videos it was based on, date) with its own link. The browser remembers the fan's answer links.
- **One list, "Your questions",** on the home page: recent questions, with saved ones pinned. Not separate history, collections and shortlist screens.
- **The reason to return:** when he publishes a video relevant to a saved answer, the list shows "1 new video since you asked", and the answer offers "Ask again with his latest videos". Checking costs no model call.
- **Later (needs accounts):** alerts, sync across devices, and a shortlist of his picks, which belongs with affiliate links.

## v1 features

**In:** the ask box with starter questions; the answer page; the source sheet; the status chips and Sponsored tag; save and "Your questions"; a share link; a small "Something wrong?" link that flags an answer for review.

**Out:** multi-turn chat, suggested follow-ups, accounts, notifications, a product browser, affiliate buttons, timestamps, retrieval or reasoning details, a creator avatar or persona. The creator's question log is not a fan feature.

## Engine changes it needs

A streaming endpoint; a `sponsored` flag on each verified source, set in code from the sponsor markings, never by the model; a `changed_mind` field beside `coverage`; answer snapshots in the database. Changes to answers go through `askthe eval`.

## Screens (phone)

```
HOME                            ANSWER
┌────────────────────────────┐  ┌────────────────────────────┐
│ Ask The Iron Snail         │  │ ‹ "3335s or the 1907s?" ☆ ⤴│
│ Answers only from his      │  │ ┌────────────────────────┐ │
│ videos, quoted and dated.  │  │ │ [His view changed]     │ │
│ ┌────────────────────────┐ │  │ │ Mostly yes, with       │ │
│ │ Ask about boots, denim…│ │  │ │ caveats; by 2023 he    │ │
│ └────────────────────────┘ │  │ │ was less sure.         │ │
│ Try:                       │  │ └────────────────────────┘ │
│ › 1907 vs the 875s?        │  │ 2022: the 3335s won [1]…   │
│ › Best budget t-shirt?     │  │ 2023: less sure [4]…       │
│ › Blundstones on a hike?   │  │ From 3 videos, newest first│
│ Your questions             │  │ [thumb] Selling 80% of my… │
│ ★ 3335s or 1907s?          │  │   7 Sep 2023 · Newest      │
│   • 1 new video since      │  │   [4] "…still might be"    │
│   Treat boots out of box?  │  │ [thumb] Why the 3335s…     │
└────────────────────────────┘  └────────────────────────────┘

SOURCE SHEET (tap [1])          NOT COVERED
┌────────────────────────────┐  ┌────────────────────────────┐
│ Listen for:                │  │ [Not covered]              │
│ "They beat my Blundstones, │  │ He hasn't covered Gucci    │
│  they beat the 1907s…"     │  │ jeans in his videos yet.   │
│ [thumb] Why the Red Wing   │  │ Closest: $260 LVC jeans    │
│ 3335s Are Better · 2022    │  │ aren't worth it unless     │
│ [ ▶ Watch on YouTube ]     │  │ you're a mega fan [1]      │
└────────────────────────────┘  └────────────────────────────┘
```

## Open questions

1. Is "web chat" in M6 flexible enough for one answer page per question?
2. Answers run 250–500 words. Keep that on phones, or tune toward a short verdict plus about 200 words (an eval-checked change)?
3. Stream the answer with grey, unverified citations, or wait about 25 s and show it fully verified?
4. Affiliate placeholders in the creator demo, or keep v1 clean and pitch them separately?
5. His name and thumbnails in the private demo before he agrees (principle 6), or a neutral frame until then?

**Sources:** [Perplexity design breakdown](https://www.925studios.co/blog/perplexity-design-breakdown), [NotebookLM help](https://support.google.com/notebooklm/answer/16179559?hl=en), [AI Overviews link cards](https://www.seo-day.de/news/article/google-ai-mode-ai-overviews-sliding-carousel-for-link-cards?lang=en), [AI Overviews click-through](https://seojuice.io/blog/google-ai-overviews-cause-massive-drop-in-search-clicks), [Consensus Meter](https://consensus.app/home/blog/introducing-the-consensus-meter/), [RTINGS changelog](https://www.rtings.com/tv/tests/changelogs/1-8), [YouTube Ask](https://tomsguide.com/how-to/youtube-now-lets-you-ask-its-ai-questions-about-videos-heres-how-it-works), [Delphi reactions](https://dewey-labs.beehiiv.com/p/delphi-alternatives), [Amazon Rufus](https://aboutamazon.com/news/retail/amazon-rufus), [Arc Browse for Me](https://windowsreport.com/arc-browser-browse-for-me/). Several are secondhand write-ups rather than hands-on use.
