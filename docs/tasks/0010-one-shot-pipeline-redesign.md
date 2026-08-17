# Task 0010: Redesign the generation pipeline for one-shot completion

**Status:** Done -- executed 2026-08-17. `generate_subtopic_cards` now fans out
per subtopic *group* and runs linked tiers sequentially, passing lower-tier
card bodies as `builds_on` (full bodies, not summaries -- the open question
below was resolved that way during implementation). `gate_and_persist` now
also generates and persists questions (via `asyncio.gather`, same semaphore)
after cards, so a topic isn't reported done until both exist. Covered by
`tests/test_generation_pipeline.py` and `tests/test_langchain_impl.py`.

**Owner:** unassigned

**Background reading:** [ADR-0026](../adr/0026-one-shot-generation-to-completion.md),
then [ADR-0007](../adr/0007-curriculum-driven-generation.md) and
[ADR-0024](../adr/0024-langgraph-for-card-generation-pipeline.md) for what this changes.

## The problem

`generation/pipeline.py` today stops after cards persist -- there's no questions node, and
nothing threads a linked difficulty tier's actual card content into the next tier's
generation call (only titles, for dedup). ADR-0026 asks for both, plus dropping the
refill-oriented framing (a subtopic's `min_cards` is still a real coverage threshold, but
nothing should ever re-trigger generation for a topic that's already run once).

## What to do

- **Linked-tier content threading.** For a `subtopic_group_id`'s tiers, when generating a
  higher tier's cards, pass the lower tier's actual card bodies (not just titles) as
  context so higher-tier cards can build on them. Needs a concrete decision on *how much*
  to pass (a subtopic can have up to 25 cards per tier) -- full bodies, summaries, or a
  subset. Update `generate_cards`'s signature/prompt (`_CARDS_SYSTEM`/`_CARDS_USER` in
  `langchain_impl.py`) accordingly; update `FakeContentGenerator` to match.
- **Questions node.** Add a `generate_questions` node to the graph, after
  `gate_and_persist` (or fanned out per subtopic/difficulty alongside it -- decide based on
  whether questions should block card-serving; ADR-0026 says cards go live as soon as their
  own batch completes, independent of when questions finish). Wire it to
  `ContentGenerator.generate_questions` (already exists in `generation/base.py`, unused
  until now) and persist `Question` rows. Check `content-model.md`'s quiz schema section
  for the target shape.
- **Drop the refill framing** in `resolve_and_plan_topic`/`generate_subtopic_cards`: these
  currently handle "topic already has some subtopics/cards, top up what's missing" as a
  general case. Per ADR-0026 a topic only ever reaches the pipeline once (post ADR-0025
  matching), so this can simplify to "topic has no curriculum yet, no cards yet, no
  questions yet -- generate all of it." Confirm with whoever's doing task 0009 how the two
  changes fit together (matching decides whether a topic reaches the pipeline at all; this
  task decides what happens once it does).
- Update `generation-pipeline.md`'s graph diagram and prose once the code matches.

## Hand back

Pipeline produces cards and a question bank for a topic in one run, linked tiers build on
each other's content, tests updated (`FakeContentGenerator` covers the new
`generate_questions` wiring and content-threading).

## Timebox

Not started. Rough guess: 1-1.5 days -- the questions node is mostly plumbing (the
generator interface already exists), the content-threading design decision is the part
that needs actual thought.
