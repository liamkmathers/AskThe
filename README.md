# AskThe

**Ask a creator's whole back catalogue a question, and get their own answer, with a link to the exact moment they said it.**

AskThe turns a niche creator's videos into a structured, searchable knowledge base of their verdicts and recommendations. Fans ask in plain language and get an answer grounded only in what the creator actually said, with timestamped links back to the source videos.

AskThe is a template. Each creator gets their own instance, framed around them and their subject:

- **Ask The Iron Snail**: men's clothing and gear (jackets, denim, boots). This is the first instance.
- Ask The *next creator*: same engine, new config, onboarded in days, not weeks.

## North Star

> **Every fan question gets the creator's own answer, from the exact moment they said it.**

We measure it as the share of questions that are either answered correctly with a working timestamp link, or correctly marked "not covered".

## Current phase

**Phase 1: Private prototype.** We're proving the assistant can answer 20 real fan questions from about 50 Iron Snail videos, with at least 18 correct and every answer linked to the clip. The prototype is private and for testing only. See [ROADMAP](docs/ROADMAP.md).

## Docs

| Doc | What it's for |
| --- | --- |
| [VISION](docs/VISION.md) | Why this exists, who it serves, the principles we don't bend |
| [ROADMAP](docs/ROADMAP.md) | Phases, the gate each must pass, Phase 1 milestones |
| [PROTOTYPE_SPEC](docs/PROTOTYPE_SPEC.md) | What Phase 1 must do, what it won't, how it's demoed |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | The pipeline, the swappable-component design, the recommended stack |
| [DATA_MODEL](docs/DATA_MODEL.md) | Creators, videos, segments, products, verdicts, and how opinions change over time |
| [EVALUATION](docs/EVALUATION.md) | How we know it works: the test set, scoring, extraction checks |
| [DECISIONS](docs/DECISIONS.md) | What we decided, why, and what we rejected |
| [RISKS_AND_QUESTIONS](docs/RISKS_AND_QUESTIONS.md) | What could go wrong, and what's still undecided |
| [CLAUDE.md](CLAUDE.md) | Rules for coding agents working in this repo |
