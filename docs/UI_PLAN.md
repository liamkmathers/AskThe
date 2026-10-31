# UI plan (M6)

*2026-10-29, decisions added 2026-10-30. **v1 built** (`askthe serve`, code in `askthe/app/`); catalog and creator header added 2026-10-30. Researched from existing products (sources at the end), and from the real answers in `eval/runs/`.*

## Direction

**One question, one answer page,** built so a chat thread can be added later (see Decisions). The engine answers each question on its own, and a page per answer is easy to save, share and come back to. Mobile first, because fans arrive from a link in his YouTube descriptions. **No thumbnails:** videos are shown by title and date.

## What we borrow, and what we avoid

| Product | Take | Avoid |
| --- | --- | --- |
| Perplexity | Citation numbers in place; answer first, then evidence | Source cards pushing the answer down; generic suggested follow-ups |
| NotebookLM | Tapping a citation shows the exact passage; saved answers keep their citations | |
| Google AI Overviews | | Answering so fully that nobody clicks through: "Watch on YouTube" is the main action |
| Consensus | One glanceable signal before the detail | |
| Wirecutter | A decisive pick in plain words; open notes when a pick changes | |
| RTINGS | Dated, visible revisions | |
| YouTube "Ask" | Sources as familiar video cards (title, date; no thumbnails, see Decisions) | |
| Delphi-style clones | | A persona instead of evidence (answers do speak as the creator since D26, but every claim is cited) |
| Amazon Rufus | Tappable starter questions | The shopping funnel |
| Arc Search | The answer as a page with its own link | Hiding which sources were read |

## The flow

1. **Home:** one input ("Ask about boots, denim…") and three starter questions taken from real fan comments.
2. **Waiting, shown honestly:** "Thinking…" → "Reading 4 videos" with their titles → the answer streams in as it's written (Sonnet: about 14 s in all). Citation numbers stay grey until code has verified the quote, then become tappable; a citation that fails is removed when the answer completes.
3. **Answer page:**
   - a verdict card: the answer's own first line ("Mostly yes, with caveats…") and at most one chip: *His view changed*, *Partly covered* or *Not covered*;
   - the reasoning, with [n] citations, nothing collapsed;
   - sources grouped by video, newest first: title, date, then that video's quotes. Sponsored quotes get a grey *Sponsored* tag.
4. **Tapping [n]** opens a sheet: the quote, large ("Listen for: '…'", since there are no timestamps, D12), then the paragraph around it with the quote highlighted ("In context", about 60 words a side, verbatim), so a reader can judge what it was part of; the video's title and date, and a full-width **Watch on YouTube** button.
5. **Not covered** is a calm short card, not an error: "He hasn't covered Gucci jeans in his videos yet", plus the one closest thing he did cover (D19).

## Keeping and coming back

- **No accounts in v1.** Each answer is stored on the server as a snapshot (question, answer, sources, the videos it was based on, date) with its own link. The browser remembers the fan's answer links.
- **One list, "Your questions",** a tab of the creator page: recent questions, with saved ones pinned. Not separate history, collections and shortlist screens.
- **The reason to return:** when he publishes a video relevant to a saved answer, the list shows "1 new video since you asked", and the answer offers "Ask again with his latest videos". Checking costs no model call.
- **Later (needs accounts):** alerts, sync across devices, and a shortlist of his picks, which belongs with affiliate links.

## v1 features

**In:** the ask box with starter questions; the answer page; the source sheet; the status chips and Sponsored tag; save and "Your questions"; a share link; a small "Something wrong?" link that flags an answer for review.

**Out:** multi-turn chat, suggested follow-ups, accounts, notifications, a product browser, affiliate buttons, timestamps, retrieval or reasoning details, a creator persona. The creator's question log is not a fan feature.

## Engine changes it needs

A streaming endpoint; a `sponsored` flag on each verified source, set in code from the sponsor markings, never by the model; a `changed_mind` field beside `coverage`; answer snapshots in the database. Changes to answers go through `askthe eval`.

## Catalog and creator page

*Added 2026-10-30, from Liam: the landing should be about the creator, and "Ask" is the brand, with an instance per creator ("Ask The Iron Snail", later others).* Every element has to serve the fan and reflect well on the creator; nothing decorative.

- **Catalog (`/`):** the wordmark "Ask.", one line on what it is, and a grid of creator cards (one column on phones, up to three wide). A card is the creator's avatar (their channel picture; initials in a circle when there's none), the instance name, the tagline (what they cover) and the number of videos answers draw on (how much there is to ask). Nothing from the bio: the card only has to say who and what.
- **Creator page: three views, one job each.** *Revised 2026-10-30 after Liam's review: the bio, the ask box and the history on one page read as cluttered.* Every view shares one header (a small "Ask." link back to the catalog; avatar, instance name, tagline) and a quiet tab bar, and each has its own address, so a link can open any of them:
  - **Ask (`/<slug>`)**: the ask box, "Answered only from his N videos, quoted and dated." and the starters. Nothing else, so a fan arriving from a video link sees what to do on the first screen.
  - **About (`/<slug>/about`)**: who the creator is as a whole: the bio's summary (`askthe bio`; until one exists, `about` from the config), their links (`links` in the config: a channel, a store; YouTube is one link among others), **Journey** (dated milestones, oldest first, on a light timeline) and **Ventures** (their own brands, products and collaborations, as compact cards). Each item's numbered citations open the source sheet with the quote, the video's title and date, and Watch on YouTube; a line says everything there comes from their own videos. It ends with one button back to asking.
  - **Your questions (`/<slug>/questions`)**: the fan's questions, saved ones pinned, with "N new videos since you asked". The tab appears only once the fan has asked something.
- **Not shown:** the channel's own description (a bio is about the creator as a whole, not one platform) and the channel banner (crops badly on phones and adds nothing a fan needs).
- **Your questions** are kept per creator in the browser (`askthe.history.<slug>`). A list saved under the old single key is filed under each answer's creator on the first visit, then the old key is removed; answers the server doesn't serve are dropped.
- **Answer pages** keep their `/a/<id>` links; the back link goes to the answer's own creator.

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
│ Your questions             │  │ Selling 80% of my boots…   │
│ ★ 3335s or 1907s?          │  │   7 Sep 2023 · Newest      │
│   • 1 new video since      │  │   [4] "…still might be"    │
│   Treat boots out of box?  │  │ Why the 3335s Are Better…  │
└────────────────────────────┘  └────────────────────────────┘

SOURCE SHEET (tap [1])          NOT COVERED
┌────────────────────────────┐  ┌────────────────────────────┐
│ Listen for:                │  │ [Not covered]              │
│ "They beat my Blundstones, │  │ He hasn't covered Gucci    │
│  they beat the 1907s…"     │  │ jeans in his videos yet.   │
│ Why the Red Wing 3335s     │  │ Closest: $260 LVC jeans    │
│ 3335s Are Better · 2022    │  │ aren't worth it unless     │
│ [ ▶ Watch on YouTube ]     │  │ you're a mega fan [1]      │
└────────────────────────────┘  └────────────────────────────┘
```

## Decisions

*From Liam, 2026-10-30.*

1. **One answer page per question for v1, built so a chat thread can be added later.** Each answer is stored as its own record with an optional link to the answer it follows up (unused in v1); the engine's `ask` gets an optional conversation history parameter later, and the page can then grow an "Ask a follow-up" box without a redesign.
2. **Keep today's answer length.** The verdict card carries the short answer; the detail stays below it. Revisit if users skip it.
3. **Stream the answer as it's written; verify after.** Text appears as it's generated with citation numbers greyed; once the answer completes, code verifies every quote, verified citations become tappable, and any that fail are removed (rule 2 still holds for what remains on the page).
4. **No affiliate links or placeholders in v1.** Pitched separately.
5. **No video thumbnails at all; his name is used** in the private demo ("Ask The Iron Snail"). Sources show the video title and date.

**Sources:** [Perplexity design breakdown](https://www.925studios.co/blog/perplexity-design-breakdown), [NotebookLM help](https://support.google.com/notebooklm/answer/16179559?hl=en), [AI Overviews link cards](https://www.seo-day.de/news/article/google-ai-mode-ai-overviews-sliding-carousel-for-link-cards?lang=en), [AI Overviews click-through](https://seojuice.io/blog/google-ai-overviews-cause-massive-drop-in-search-clicks), [Consensus Meter](https://consensus.app/home/blog/introducing-the-consensus-meter/), [RTINGS changelog](https://www.rtings.com/tv/tests/changelogs/1-8), [YouTube Ask](https://tomsguide.com/how-to/youtube-now-lets-you-ask-its-ai-questions-about-videos-heres-how-it-works), [Delphi reactions](https://dewey-labs.beehiiv.com/p/delphi-alternatives), [Amazon Rufus](https://aboutamazon.com/news/retail/amazon-rufus), [Arc Browse for Me](https://windowsreport.com/arc-browser-browse-for-me/). Several are secondhand write-ups rather than hands-on use.
