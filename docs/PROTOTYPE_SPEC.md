# Phase 1: Prototype spec

A private demo that proves the assistant can answer real fan questions accurately, with sources, from one creator's videos. It's built to be shown to the creator, not released. It's for testing only and isn't monetised.

## Scope

- **One creator:** The Iron Snail (instance name: *Ask The Iron Snail*).
- **About 50 videos**, chosen as described in [ROADMAP](ROADMAP.md#choosing-the-50-videos).
- **A simple chat interface** for the demo, plus a command line for development and evaluation.

## Must have

- [ ] Ingest videos with their transcripts, titles and publish dates.
- [ ] Extract the useful knowledge, not just raw text: which product, what the creator thinks of it, what it's good or bad for, rough price if mentioned, and where in the video it's said.
- [ ] Answer questions in plain language using only the creator's content.
- [ ] Every answer shows its sources as links that open the video at the right moment.
- [ ] Say clearly when the creator hasn't covered something, instead of inventing an answer.
- [ ] Prefer the most recent opinion, and mention when the creator changed their mind.
- [ ] Handle comparison questions ("X or Y for winter?").
- [ ] Make it easy to add more videos or a new creator later without rebuilding.

## Nice to have

- [ ] Product links where an affiliate link would later go (placeholders are fine).
- [ ] A simple list of the questions asked during testing, as a preview of the creator dashboard.
- [ ] A browsable view of all products the creator has reviewed, with their verdicts.

## Out of scope

- Imitating the creator's voice, personality or speaking style.
- Public launch, user accounts, payments, real affiliate integration.
- More than one creator at a time. (The code must *support* more; we just don't run more.)

## What a good answer looks like

For "Which boots does he recommend for wet winters, and which ones did he say fell apart?":

1. **The verdict first**, in plain language: which boots, and the one-line reason.
2. **The reasoning**, briefly, as the creator gave it.
3. **Sources**: each claim tied to a video title, its publish date, and a link that opens at the moment it was said.
4. **Time awareness**: if a later video changed the verdict, the answer leads with the newer one and says what changed.
5. **Honest gaps**: if part of the question isn't covered ("he hasn't reviewed any boots for wet winters"), it says so plainly.

The answer refers to the creator in the third person ("The Iron Snail recommends…", "he said…"). It never speaks *as* the creator.

## Acceptance test

A test set of 20 real fan questions, taken from the channel's comments. The prototype passes when:

- at least **18 answers are correct**,
- **every answer has a working timestamp link**, and
- the questions with no answer in the videos are **recognised as not covered**.

How questions are collected and scored is in [EVALUATION](EVALUATION.md).

## Demo for the pitch

A 2-minute screen recording showing:

1. Three or four real fan questions, each answered with the verdict and a click into the exact clip.
2. One comparison question.
3. One "he changed his mind" answer.
4. One honest "not covered yet".
