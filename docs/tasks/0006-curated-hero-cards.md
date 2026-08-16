# Task 0006: A real curated `is_hero` flag

**Owner:** unassigned

## The problem

ADR-0017 introduced hero-styled cards — larger type, left accent border, never
collapsed — as visual anchors in the feed. v1 ships a placeholder heuristic: the
**first card in each feed station** renders as hero, purely a feed-layout decision,
not a property of the card.

This is a known-weak stand-in. A subtopic's first-generated card is not reliably its
most important idea — it's just whichever card the model or fixture happened to write
first. There's no actual curation or judgment behind which cards get the hero treatment.

## Why it matters

Hero cards are meant to read as "the one thing to remember about this subtopic." A
wrong or arbitrary hero undermines exactly the effect it's meant to create — a user who
learns to distrust which card is "the important one" stops treating hero styling as a
signal at all.

## What to do

Design a real `is_hero` signal — likely LLM-judged at generation or curriculum time
(similar in spirit to `difficulty`'s independent verification, not a self-report), or
possibly a lightweight curation step where a human flags one card per subtopic. Needs:

- A concrete definition of "hero-worthy" a judge (human or model) can apply consistently
  — content-model.md doesn't have one today.
- A cap: likely one hero per subtopic, not per station (a station can span multiple
  subtopics in the mixed feed).
- A migration replacing the "first in station" client-side heuristic in `Feed.tsx`/
  `lib/stations.ts` with a real `card.is_hero` (or similar) field read from the API.

## Hand back

A design note or ADR for the hero-selection mechanism, plus the schema/migration and
the `Feed.tsx`/`stations.ts` change to consume it instead of the current heuristic.

## Timebox

Not started. Rough guess: half a day for the design decision, half a day for the
plumbing — contingent on which selection mechanism gets picked.
