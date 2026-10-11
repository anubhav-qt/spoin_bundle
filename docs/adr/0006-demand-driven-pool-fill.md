# ADR-0006: Demand-driven pool fill with degraded serving and hysteresis

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav
- **Amended by:** [ADR-0007](0007-curriculum-driven-generation.md) -- the coalescing lock key
  becomes `(subtopic_id)` rather than `(topic_id, difficulty)`, and the starvation signal
  becomes "this subtopic is below `min_cards`" rather than "this topic's pool is low".
  Further amended by [ADR-0026](0026-one-shot-generation-to-completion.md) -- the fill-
  triggering mechanism itself (point 2 in the Decision below, and ADR-0007's coalescing
  lock) is dropped: generation is now a one-shot run per topic to a fixed card+question
  budget, not an ongoing refill loop. **What ADR-0026 does NOT resolve:** whether the
  feed-serving behavior described here (degraded mode, hysteresis, points 1/3/4 below)
  still applies during a topic's initial one-shot run -- see ADR-0026's "Open question."
  The body below is left as originally written; read ADR-0026 alongside it.
  Further amended by [ADR-0106](0106-typescript-on-hono-and-the-authoring-harness.md) --
  a topic's cards are written once and only reported cards are rewritten, so a starved
  stratum is never filled; the feed still serves short rather than backfilling (point 1),
  and a topic read to the end recycles its read cards with `recycling` set.

## Context

The feed targets a difficulty mix per user level (see
[content-model.md](../architecture/content-model.md)). Under a thin corpus and free-tier
generation quota, the pool for a given `(topic, difficulty)` slot will frequently lack
enough unseen cards to satisfy that mix. This is the normal case at launch, not an edge case.

Three options were on the table when a slot is starved: backfill with the current
difficulty, serve a shorter page, or relax the seen-filter and repeat cards.

## Decision

**Serve degraded rather than wrong, repair asynchronously, recover on a threshold.**

1. **Keep the mix honest.** Do not silently substitute another difficulty. Serve a
   shorter page.
2. **Trigger an async fill** for the starved slot on detection. Generation follows real
   demand rather than a static plan.
3. **Hysteresis: two thresholds.** Enter degraded mode below `POOL_LOW`, exit only above
   `POOL_HIGH`, with a deliberate gap between them.
4. **Honest end-of-feed state.** "More coming soon", never an indefinite spinner.

### Why two thresholds and not one

With a single threshold the system flaps. The pool sits on the line, one card generates,
degraded mode exits, the user immediately consumes that card, degraded mode re-enters.
Every crossing re-triggers work and the state oscillates. The gap between `POOL_LOW`
and `POOL_HIGH` is what makes the state stable.

### Job coalescing is mandatory

If 50 users hit the same starved slot within a minute, the naive implementation enqueues
50 identical fill jobs and spends an entire day of quota on one topic.

**Fill jobs carry a uniqueness lock on `(topic_id, difficulty)`.** Concurrent misses
collapse into one queued job. `procrastinate` supports this directly via queueing locks.
This is not an optimization; without it the first popular topic exhausts the daily budget.

### Fairness cap

Demand-driven generation plus a hard daily quota means a small number of users with
niche topics can consume the entire day's budget and starve everyone else.

- Fill priority is **weighted by subscriber count** for that topic.
- Fills per topic per day are **capped**.

This also reinforces the core economics: shared topics naturally outrank private ones,
which is exactly the behaviour ADR-0004 exists to produce.

### Priority ordering

A demand-triggered fill has a real user waiting on it and outranks speculative background
fills. It slots into the priority queue established in ADR-0003.

## Consequences

**Easier**

- Generation follows actual demand instead of guessing, which matters enormously when
  the daily budget is tiny.
- Users never receive content at the wrong difficulty, which is the failure mode most
  likely to read as "this product is broken".
- Coalescing and fairness are things we would need at scale regardless. The constraint
  forces them early.

**Harder**

- The feed service now has **state** (degraded or not, per slot) rather than being a pure
  function of the corpus. More to reason about and more to test.
- Degraded mode can persist for hours. Cron runs every ~15 minutes and the daily quota
  may already be spent, so a fill triggered at 2pm might not land until tomorrow. UI copy
  must not imply imminent arrival.
- Short pages on a swipe feed read as "I reached the end". The end-of-feed state is a
  real design surface, not an error state, and deserves actual design attention.

**Committed to**

- `POOL_LOW` and `POOL_HIGH` are config values, tuned against observed consumption.
- Every fill job is idempotent and coalescible. No fill path may bypass the lock.

## Alternatives considered

**Backfill with the current difficulty.** The boring, safe answer, and invisible to the
user. Rejected because it silently destroys the mix, including the upward slice that is
the promotion signal, and hides pool starvation from us precisely when we most need to
see it.

**Relax the seen-filter and repeat cards.** Cheapest of all. Rejected: on a feed product,
visibly repeating content is a stronger negative signal than running out.

**Pre-generate everything on a static schedule, no demand signal.** What the previous
iteration attempted. It cannot know which topics matter, so it spends scarce quota on
topics nobody reads.

## Revisit when

- Degraded mode becomes common enough to be the default experience. That is a signal to
  raise generation capacity (paid tier) rather than to tune thresholds.
- The fairness cap starts blocking legitimate demand from real users rather than
  long-tail noise.
- Observed flapping despite hysteresis, meaning the gap is too narrow.
