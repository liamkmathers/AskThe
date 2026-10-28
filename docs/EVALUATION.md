# Evaluation

How we know the assistant works, and how we notice when a change makes it worse.

Two things are measured separately: **extraction** (did we capture what the creator said?) and **answers** (did fans get the right, cited answer?). A bad answer can come from either, and we need to know which.

## 1. Answer evaluation: the Phase 1 gate

### Building the test set

- **20 real fan questions** from comments and community posts on the creator's channel, lightly cleaned for typos but not rewritten.
- A **mix** of question types, roughly:
  - 8 product lookups ("best boots under $300?", "best value t-shirt?")
  - 4 comparisons ("X or Y for winter?")
  - 3 change-of-mind or long-term ("does he still like…?")
  - 2 how-to or advice ("how do I break in…?")
  - 3 not covered (topics genuinely absent from the ingested videos)
- Each question is written down with the **expected answer**: key facts, the products involved, and the video(s) and rough timestamps that support it. For "not covered" questions, the expected answer is "not covered" and a note on why.
- Collect the questions **before** tuning the system on them, and keep them out of prompt examples.

Stored as `eval/questions/<creator>.yaml`:

```yaml
- id: q07
  question: "Which boots does he recommend for wet winters?"
  source: https://www.youtube.com/watch?v=...&lc=...   # the comment
  type: lookup
  expected:
    covered: full
    must_mention: ["Product A", "Product B"]
    must_not_claim: ["Product C is waterproof"]
    sources: [{video: abc123, near_s: 312}]
  notes: "He revised Product A in the 2025 long-term review."
```

### Scoring each answer

| Check | How | Automated? |
| --- | --- | --- |
| **Correct** | Matches the expected facts; no claim the creator didn't make; newest verdict first where relevant | Human judgement, helped by an LLM grader that flags likely problems |
| **Cited** | Every answer has at least one timestamp link | Yes |
| **Links work** | Each link points to a real ingested video, and the timestamp lands within a few seconds of a segment containing the supporting text | Yes |
| **Coverage right** | "Not covered" questions get "not covered"; covered questions don't | Yes |

**Gate:** at least 18 of 20 correct, all links working, every not-covered question recognised.

### Runs

`askthe eval` runs the whole set and saves `eval/runs/<date>-<label>.json` with each answer, its scores, and the pipeline versions used. Runs are compared side by side, so a prompt change that fixes one question and breaks two is visible.

## 2. Extraction evaluation

- **Hand-label 5 videos** of different types (including at least one explainer and one with a sponsor read): write down the video's purpose and thesis, its sponsor and aside segments, and every claim a careful viewer would note.
- **Profile check:** does the extractor's profile get the purpose, type and thesis right? Are sponsor segments caught? A wrong profile skews every claim after it.
- **Sponsorship check:** no claim from a sponsor segment is marked as an unsponsored verdict (automated against the labels).
- **Attribution check:** claims voiced by others ("people say…", a brand's own claim) are not marked as held by the creator; in-video corrections are caught.
- **No guessed names:** every resolved entity is supported by the transcript, title, description or glossary.
- Compare the extractor's output against them:
  - **Recall:** how many hand-labelled claims were captured. This matters most: a missed claim is an unanswerable question.
  - **Precision:** how many extracted claims are real and correctly stated. A wrong claim is a misquote.
  - **Quotes check:** every extracted quote must appear in the segment it cites (automated).
- **Entity resolution check:** list merged entities and their aliases; look for wrong merges (two products as one) and missed merges (one product as two).

## 3. Gap signals

These tell us when the schema is too narrow:

- **Coverage report:** per video, stretches of transcript longer than about 2 minutes that produced no claims. Reviewed by hand; often intros or sponsor reads, sometimes missed knowledge.
- **Raw-only answers:** test questions answered correctly only via raw segment search, with no matching claim. Each one is a candidate new field or claim kind.
- **Overflow review:** what's accumulating in `attributes` and in claims of kind `other`. Frequent patterns get promoted to proper fields.

## When to run what

| Change | Run |
| --- | --- |
| Extraction prompt or schema | Extraction eval on the 5 labelled videos, then full answer eval |
| Retrieval or answer prompt | Full answer eval |
| New videos ingested | Quotes check and coverage report on the new videos |
| Any adapter swap | Full answer eval; results should not get worse |
