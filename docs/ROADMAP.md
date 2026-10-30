# Roadmap

Each phase answers one question. No phase starts until the one before it passes its gate, so the only commitment right now is **Phase 1**.

Targets are proposed starting points. We'll adjust them once real numbers come in.

| Phase | Question it answers | Gate to move on | Status |
| --- | --- | --- | --- |
| 1. Private prototype | Can it answer fan questions accurately from transcripts? | 20 real fan questions, at least 18 correct, every answer quoting and linking its source videos, uncovered questions recognised as such | **Current** |
| 2. Creator pitch | Does a creator want it? | Iron Snail (or another gear creator) agrees to a pilot | Not started |
| 3. Public pilot | Do fans use it and does it make money? | Fans return to ask more; affiliate clicks and clicks back to videos are measurable | Not started |
| 4. Second creator | Is the pipeline repeatable? | A new creator onboarded in days, not weeks | Started: J. Kenji López-Alt (cooking), config in `creators/kenji.yaml`; videos not yet fetched |
| 5. Vertical | Is there a bigger product across creators? | Several creators in one niche live and opted in | Not started |

## Phase 1 milestones

Each milestone ends with something we can run and check. The spec is in [PROTOTYPE_SPEC](PROTOTYPE_SPEC.md) and the design in [ARCHITECTURE](ARCHITECTURE.md).

| # | Milestone | Done when |
| --- | --- | --- |
| M0 ✅ | **Skeleton** | Repo layout, config loading, core interfaces and domain models in place; Iron Snail creator config written; tests run |
| M1 | **Ingest** | About 50 chosen videos have metadata and transcripts cached locally; the database rebuilds from that cache with one command. *Done for 22 of 50 videos; the rest are being fetched locally (YouTube rate-limits).* |
| M2 | **Understand** | Every video has a profile: what it is, its sections, entities, sponsor reads and asides located precisely, and the questions it answers (D15). *Done for 3 videos in a trial (about $0.19 each); run for the rest once all 50 are fetched.* |
| M3 | **Answer** | `askthe ask` answers a question by reasoning over the full transcripts, with cited, verified quotes; says "not covered" when it should; prefers the newest verdict and flags changes of mind; handles comparisons. *Working: hybrid retrieval (D16) and full mode both answered the first three real questions correctly, every quote verified. Vector search is live (22 videos embedded for about $0.002) but changed no answer on those questions; it is judged on the M4 test set.* |
| M4 ✅ | **Test set and eval harness** | 20 real fan questions collected from comments, with expected answers; one command scores a full run and saves the results. *Done: harness built (`askthe comments`, `questions`, `eval`) and 23 real fan questions reviewed. Baseline hybrid answers were 18/20 correct on review (D19 fixed the two misses). After D19, two runs on 35 videos: every automated check passes in both modes and every citation holds; hybrid reads about 3,400 words a question and 66–69% of what full mode cites, at $0.09 a question (full: $0.09 warm, $1.15 cold).* |
| M5 | **Iterate to the gate** | At least 18 of 20 correct, all citations holding, uncovered questions recognised |
| M6 | **Chat UI and demo** | A simple web chat shows answers, quotes, video dates and links to the videos; the 2-minute demo is recorded. *Page built (`askthe serve`, [UI_PLAN](UI_PLAN.md)): a catalog of creators, a page per creator, one answer page per question, streamed then verified; demo not yet recorded.* |

Milestones M4 can start in parallel with M2 and M3: collecting real questions early shows what answering needs to handle.

**Nice-to-haves**, if time allows after M5: affiliate link placeholders on products, a log of asked questions (dashboard preview), a browsable product and verdict list, and the comment uses parked in D18 (his own replies as content, nickname mining, demand from comments).

## Choosing the ~50 videos

The set must exercise every behaviour the gate tests:

- Single-product reviews (the bulk).
- Comparisons and "X vs Y" videos.
- Buying guides and "best of" round-ups.
- Long-term and re-review videos, so changes of opinion can be tested.
- A few how-to videos (care, break-in), for non-product questions.
- A spread of publish dates, so "newest verdict wins" is tested.

Pick the test-set questions (M4) and the videos together: the questions with answers need their source videos in the set, and the "not covered" questions need topics that are genuinely absent.
