# Roadmap

Each phase answers one question. No phase starts until the one before it passes its gate, so the only commitment right now is **Phase 1**.

Targets are proposed starting points. We'll adjust them once real numbers come in.

| Phase | Question it answers | Gate to move on | Status |
| --- | --- | --- | --- |
| 1. Private prototype | Can it answer fan questions accurately from transcripts? | 20 real fan questions, at least 18 correct, every answer quoting and linking its source videos, uncovered questions recognised as such | **Current** |
| 2. Creator pitch | Does a creator want it? | Iron Snail (or another gear creator) agrees to a pilot | Not started |
| 3. Public pilot | Do fans use it and does it make money? | Fans return to ask more; affiliate clicks and clicks back to videos are measurable | Not started |
| 4. Second creator | Is the pipeline repeatable? | A new creator onboarded in days, not weeks | Not started |
| 5. Vertical | Is there a bigger product across creators? | Several creators in one niche live and opted in | Not started |

## Phase 1 milestones

Each milestone ends with something we can run and check. The spec is in [PROTOTYPE_SPEC](PROTOTYPE_SPEC.md) and the design in [ARCHITECTURE](ARCHITECTURE.md).

| # | Milestone | Done when |
| --- | --- | --- |
| M0 ✅ | **Skeleton** | Repo layout, config loading, core interfaces and domain models in place; Iron Snail creator config written; tests run |
| M1 | **Ingest** | About 50 chosen videos have metadata and transcripts cached locally; the database rebuilds from that cache with one command. *Done for 22 of 50 videos; the rest are being fetched locally (YouTube rate-limits).* |
| M2 | **Extract** | Every video has structured verdicts (product, stance, pros and cons, use cases, price, the quote and segment it came from); products are merged across videos; extraction is spot-checked on 5 hand-labelled videos (see [EVALUATION](EVALUATION.md)). *Code done and tested with a scripted LLM; first real run waits on an API key.* |
| M3 | **Answer** | The command line answers a question with cited, quoted sources; says "not covered" when it should; prefers the newest verdict and flags changes of mind; handles comparisons |
| M4 | **Test set and eval harness** | 20 real fan questions collected from comments, with expected answers; one command scores a full run and saves the results |
| M5 | **Iterate to the gate** | At least 18 of 20 correct, all citations holding, uncovered questions recognised |
| M6 | **Chat UI and demo** | A simple web chat shows answers, quotes, video dates and links to the videos; the 2-minute demo is recorded |

Milestones M4 can start in parallel with M2 and M3: collecting real questions early tells us what the extraction needs to capture.

**Nice-to-haves**, if time allows after M5: affiliate link placeholders on products, a log of asked questions (dashboard preview), a browsable product and verdict list.

## Choosing the ~50 videos

The set must exercise every behaviour the gate tests:

- Single-product reviews (the bulk).
- Comparisons and "X vs Y" videos.
- Buying guides and "best of" round-ups.
- Long-term and re-review videos, so changes of opinion can be tested.
- A few how-to videos (care, break-in), for non-product questions.
- A spread of publish dates, so "newest verdict wins" is tested.

Pick the test-set questions (M4) and the videos together: the questions with answers need their source videos in the set, and the "not covered" questions need topics that are genuinely absent.
