# Risks and open questions

The biggest risk isn't technical: it's whether creators say yes.

## Product and business risks

| Risk | Why it matters | How we handle it |
| --- | --- | --- |
| Creator says no | No permission, no product | Keep the prototype private; pitch with a demo; try several gear creators |
| Misquoting the creator | A wrong answer damages his name, and ours | Answer only from sources; verify citations in code; always link the clip; admit gaps |
| Platform terms on using video content | Gathering content at scale may conflict with YouTube's rules | Private, unmonetised testing with one creator; with a partner, get content through the creator directly |
| Outdated advice | Products change, opinions change | Use publish dates; newest verdict first; show the video date |
| Fans find it gimmicky | Clone products have been mocked | No fake personality; position it as a guide to the creator's videos |
| Competitors move into the niche | Clone platforms are funded | Win on niche depth, product structure and the revenue-share deal |

## Technical risks

| Risk | Why it matters | How we handle it |
| --- | --- | --- |
| Auto-caption errors on brand and model names | "Iron Ranger" heard as "iron ringer" breaks product matching and search | Store caption kind; give the extractor the video title, description and creator categories as context; aliases on products; confidence on claims |
| Wrong product merges | Two products treated as one gives wrong verdicts | Product resolution check in evaluation; conservative merging; aliases reviewed by hand for the prototype |
| Extraction misses knowledge | Unanswerable questions | Raw transcripts stay searchable; coverage report; extraction recall measured on labelled videos |
| Sarcasm, hedging and conditional verdicts | "Great boot… if you never walk in rain" read as a plain recommendation | `context` field; answers read the surrounding transcript, not just the claim |
| Sponsored segments | Sponsored praise treated as an independent verdict | `sponsorship` claim kind; sponsorship shown in answers |
| YouTube blocked or rate-limited | Can't fetch | Fetch is a separate stage; can run on a local machine; raw files are cached so each video is fetched once |
| LLM cost and speed | Re-running extraction on many videos | Cache per video and extractor version; only re-extract what changed |

## Open questions

- [ ] Which affiliate programmes do gear creators already use, and how do commissions split today?
- [ ] Where does the assistant live in a pilot: the creator's website, a link in video descriptions, or both?
- [ ] Does the creator want final review of answers on sensitive topics such as sponsored products?

**Answered**

- [x] Iron Snail first, or a smaller gear creator? **Iron Snail first** (see [D3](DECISIONS.md#d3-the-iron-snail-first-one-creator-at-a-time)).
