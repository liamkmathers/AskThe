# Risks and open questions

The biggest risk isn't technical: it's whether creators say yes.

## Product and business risks

| Risk | Why it matters | How we handle it |
| --- | --- | --- |
| Creator says no | No permission, no product | Keep the prototype private; pitch with a demo; try several gear creators |
| Misquoting the creator | A wrong answer damages his name, and ours | Answer only from sources; verify citations in code; always quote and link the video; admit gaps |
| Platform terms on using video content | Gathering content at scale may conflict with YouTube's rules | Private, unmonetised testing with one creator; with a partner, get content through the creator directly |
| Outdated advice | Products change, opinions change | Use publish dates; newest verdict first; show the video date |
| Fans find it gimmicky | Clone products have been mocked | No fake personality; position it as a guide to the creator's videos |
| Competitors move into the niche | Clone platforms are funded | Win on niche depth, product structure and the revenue-share deal |

## Technical risks

| Risk | Why it matters | How we handle it |
| --- | --- | --- |
| Auto-caption errors on names | Seen in every test video: "Chouinard" spelled five ways, "Uniqlo" three. Breaks matching and search | Per-creator glossary; title and description as context; aliases on entities; confidence on claims |
| Products shown but not named | The creator holds an item up and says "this one"; the transcript can't say what it is | Use the video description; keep the name as said and mark it unresolved, never guess; reading on-screen text or frames is a possible later addition |
| Reported views mistaken for his | "People say it pills more" answered as his verdict | `held_by` on every claim; answers attribute other views explicitly |
| Product changed vs mind changed | A verdict on a 1988 fleece applied to today's | Product versions; claims attach to the version named |
| Sensitive claims about companies or people | Strengthening a hedged remark about ethics or a controversy damages trust and could be unfair | `certainty` and `held_by`; answers keep his hedging; personal life never extracted |
| Wrong entity merges | Two products treated as one gives wrong verdicts | Entity resolution check in evaluation; conservative merging; aliases reviewed by hand for the prototype |
| Extraction misses knowledge | Unanswerable questions | Raw transcripts stay searchable; coverage report; extraction recall measured on labelled videos |
| Sarcasm, hedging and conditional verdicts | "Great boot… if you never walk in rain" read as a plain recommendation | `context`, `aspect` and `certainty` fields; answers read the surrounding transcript, not just the claim |
| Sponsored segments | Sponsored praise treated as an independent verdict | Sponsor segments marked in the understanding pass; claims from them flagged `sponsored` and never used as verdicts |
| YouTube blocked or rate-limited | Confirmed: YouTube refuses cloud servers ("sign in to confirm you're not a bot") | Fetch is a separate stage run from a home connection; raw files are cached so each video is fetched once; transcripts can also come from files |
| No jump-to-moment links | Fans land at the start of the video and have to find the passage | Answers quote his words so the passage is recognisable; could be revisited later as an optional extra (D12) |
| LLM cost and speed | Re-running extraction on many videos | Cache per video and extractor version; only re-extract what changed |

## Open questions

- [ ] Which affiliate programmes do gear creators already use, and how do commissions split today?
- [ ] Where does the assistant live in a pilot: the creator's website, a link in video descriptions, or both?
- [ ] Does the creator want final review of answers on sensitive topics such as sponsored products?

**Answered**

- [x] Iron Snail first, or a smaller gear creator? **Iron Snail first** (see [D3](DECISIONS.md#d3-the-iron-snail-first-one-creator-at-a-time)).
