# Evaluation

How we know the assistant works, and how we notice when a change makes it worse.

Two things are measured separately: **retrieval** (did the model get the right videos?) and **answers** (did fans get the right, cited answer?). A bad answer can come from either, and we need to know which. Since D15 there is no claim extraction to measure; profiles are checked instead.

## 1. Answer evaluation: the Phase 1 gate

### Building the test set

- **20 real fan questions** from comments and community posts on the creator's channel, lightly cleaned for typos but not rewritten.
- A **mix** of question types, roughly:
  - 8 product lookups ("best boots under $300?", "best value t-shirt?")
  - 4 comparisons ("X or Y for winter?")
  - 3 change-of-mind or long-term ("does he still like…?")
  - 2 how-to or advice ("how do I break in…?")
  - at least 2 of the above about his personal taste ("what colour chinos does he like?", "which jeans does he wear himself?")
  - 3 not covered (topics genuinely absent from the ingested videos)
- Each question is written down with the **expected answer**: key facts, the products involved, and the video(s) that support it. For "not covered" questions, the expected answer is "not covered" and a note on why.
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
    sources: [abc123]
  notes: "He revised Product A in the 2025 long-term review."
```

### Scoring each answer

| Check | How | Automated? |
| --- | --- | --- |
| **Correct** | Matches the expected facts; no claim the creator didn't make; newest verdict first where relevant | Human judgement, helped by an LLM grader that flags likely problems |
| **Cited** | Every covered answer quotes the creator and links at least one video | Yes |
| **Citations hold** | Each link points to a real ingested video, and each quote appears in the cited segment of that video | Yes |
| **Coverage right** | "Not covered" questions get "not covered"; covered questions don't | Yes |

**Gate:** at least 18 of 20 correct, all citations holding, every not-covered question recognised.

### Runs

`askthe eval` runs the whole set and saves `eval/runs/<date>-<label>.json` with each answer, its scores, and the pipeline versions used. Runs are compared side by side, so a prompt change that fixes one question and breaks two is visible.

## 2. Profile and retrieval checks

- **Profiles:** on 5 videos of different types, check by hand that the purpose, type, thesis and sections are right, and that every sponsor read and aside is found and located precisely (and nothing else is). Automated: every passage's `starts_with` and `ends_with` must be found in the transcript; unlocated passages are reported.
- **Retrieval:** once the catalogue outgrows the reading budget, check for each test question that the videos holding the answer were among those read. Until then (the 50-video prototype is read in full) this is trivially true.
- **Quotes:** every citation's quote must appear in the segment it cites. Enforced on every answer; failures are counted in the eval run.

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
