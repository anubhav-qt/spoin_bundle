# ADR-0010: Feed serving — stratified selection, linear ranking, slate pagination

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav, Mayank

## Context

The feed is the product. It must serve in **under 100ms with no LLM call** (hard rule 1)
and, in v1, with **no Redis** (ADR-0003) — Postgres only.

## Decision

### Pipeline

```
per topic:  SELECT (stratified by difficulty)  ->  RANK (within strata)
                                               ->  SLATE (~25 cards)

across topics:  INTERLEAVE PLAN (affinity-weighted round-robin, 50 slots)
                              ->  page from the plan
```

### The difficulty mix is a constraint, not a score

The instinct is to fold "should be 80% beginner" into the ranking function as a weight.
This is wrong: it produces approximately-80% that drifts with the candidate pool, and it is
untestable.

Instead, **stratified sampling**: the 80% is pulled from beginner candidates and the 20%
from intermediate as separate queries, then ranked *within* each stratum. The mix becomes
exact and provable.

Diversity works the same way — a post-ranking interleave, not a score. Five excellent cards
from one subtopic is a worse page than five good cards from five subtopics, and that cannot
be expressed per-card because it depends on what preceded it.

**Principle: score individual items; enforce composition rules structurally.** Anything
about the *set* (mix, diversity, spacing) belongs outside the ranker.

### Seen-state: three states with a second-chance cycle

```
UNSEEN     never shown
DEFERRED   shown but not expanded  -> returns after the cycle completes
SEEN       expanded AND ("Got it" tapped OR dwell >= threshold)
                                   -> counts toward progression, never returns
```

- Cycle counter per `(user, topic, difficulty)`.
- Deferred cards record the cycle in which they were deferred.
- Eligible = `UNSEEN` or (`DEFERRED` and `deferred_cycle < current_cycle`).
- The cycle advances when no `UNSEEN` cards remain at that difficulty across all subtopics.

**Scrolling past never counts.** Expansion is required, so speed-swiping earns nothing.

**Beyond expansion, either an explicit "Got it" tap or a dwell threshold marks it SEEN.**

An earlier version of this ADR made expansion-plus-dwell the only path, justified as making
progression un-gameable. That justification was overstated: **the coverage gate was never
the real gate — the quiz is.** Someone who taps their way to 80% coverage takes the quiz,
fails, and receives a remediation list pointing at the cards they skipped. The system
self-corrects and the only cost falls on them.

So the coverage gate should be optimised for **low friction and honesty**, not anti-cheat:

- Fast reader, finishes in 2s -> taps "Got it", counted immediately. Their reading speed
  decides, not an arbitrary threshold.
- Normal reader -> dwell catches it. Zero friction, nothing to remember.

Explicit-only was rejected because it demands ~250 deliberate taps per tier. Users forget,
progress stalls for people who genuinely read everything, and that is indistinguishable from
a broken gate.

**Expansion rate remains a health metric.** If users expand only 20% of cards, nobody reaches
the 80% coverage gate and the quiz never unlocks for anyone. That failure presents as "users
aren't progressing", not as "our gate is unreachable". Instrument it from day one.

### Storage: table as truth, bitmap as derived read model

Seen-state is written to a **table** (`user_card_state`) which is the source of truth, and
maintained as a **derived bitmap** which is what the feed query actually reads.

Why not bitmap alone, despite the corpus being bounded (~750 cards/topic = ~94 bytes):

- Three states plus a cycle counter is not one bit.
- Bitmaps require a stable per-topic `ordinal`, which forces answers to questions the table
  answers for free: do rejected cards consume ordinals? When card v2 supersedes v1, same
  ordinal (user never sees the improvement) or new (everyone re-sees it)? With `card_id`
  these are non-questions.
- Debuggability: a user reports a repeat; with rows that is one query, with bits it is
  decoding a `bytea`.
- Analytics: "which cards get skipped most" is trivial on rows and impossible on bits.

Why not table alone:

- The anti-join is the most expensive part of the feed query and it grows with usage.
- `popcount` over the bitmap gives per-subtopic seen counts for free, which is exactly what
  the 80% progression gate needs.

**The bitmap is rebuildable from the table**, so drift is recoverable rather than fatal. A
periodic reconciliation job makes it a non-event. This is a materialized read model over an
event log, not a compromise between two options.

*This is only viable because ADR-0007 bounded the corpus. An infinite-corpus feed cannot do
this.*

### Ranking: linear, not learned

```
score = w1 * card_quality      global engagement RATE, all users
      + w2 * topic_affinity    this user's engagement per topic
      + w3 * coverage_need     prefers under-consumed subtopics, drives progression
      + w4 * freshness
      + epsilon                exploration
```

At this scale a weighted linear score beats a model: debuggable, tunable, and explainable
when output looks wrong. Weights live in **config**.

**Rate, not count.** `card_quality` is likes-per-impression, never total likes. Raw counts
make old cards permanently dominant and new cards permanently invisible. This is why
impressions must be logged ([ADR-0011](0011-engagement.md)).

**10% exploration (epsilon-greedy).** Serving only top-scored cards creates a cold-start
death spiral: new cards get no impressions, so accumulate no quality signal, so never rank,
so never get impressions. A fixed 10% of each page is chosen randomly from eligible
candidates so new content can prove itself.

### Pagination: per-topic slates plus a cheap interleave plan

Offset pagination breaks when the underlying set changes, and generation changes it
constantly. Cursor-on-id does not work either, because ordering is by a shifting score. So
we materialize a ranked slate and page from it.

**The slate is per topic, not per feed**, with a separate interleave plan on top:

```
per-topic slate    ~25 ranked card ids per subscribed topic
                   EXPENSIVE to compute, rarely invalidated

interleave plan    [topic_id x 50], affinity-weighted round-robin
                   CHEAP, regenerated freely
```

Position is a single integer into the plan, so pagination stays simple.

**Principle: cache at the layer where invalidation is rare, and keep the volatile layer
cheap enough that recomputing it is free.** Filter change, affinity shift, and slate refill
all regenerate only the plan, which requires no ranking.

#### Why per-topic rather than one combined slate

**It removes the cross-topic score normalization problem.** `card_quality` is an engagement
rate, and rates differ systematically between topics: a topic with 50 enthusiasts has a
different baseline than one with 5,000. Ranking all topics in one pool lets the "hot" topic
dominate every page regardless of the user's affinity, and fixing that requires per-topic
normalization that is fiddly and easy to get subtly wrong.

Per-topic slates make scores **only ever comparable within a topic**, where they are
commensurable. Cross-topic weighting moves to the affinity interleave, where the decision is
explicit and tunable instead of buried in score arithmetic.

**The difficulty mix composes correctly.** Each slate is stratified for *that topic's* tier,
so any interleave preserves every topic's mix. This matters because a user can be beginner
in one topic and advanced in another — which one combined slate handles awkwardly.

**Filtering never causes repeats or skips.** Per-topic slate positions persist across filter
changes, so a user can filter to one topic, read, unfilter, and resume exactly where they
were in every topic.

**Slates refill independently** rather than all-or-nothing, and topics the user is not
currently reading cost nothing to re-rank.

#### Plan generation

Weighted round-robin with deficit counters (the algorithm packet schedulers use for weighted
fair queuing). Deterministic, and a topic with 2x the affinity gets 2x the slots spread
evenly rather than clumped.

#### Sizes and lifetimes

- Slate: ~25 cards per topic, refilled below a threshold.
- Plan: 50 positions, regenerated on filter change, affinity shift, or slate refill.
- Slate TTL ~30 min, or on subscription change.

### Topic filters

Default: all subscribed topics, interleaved weighted by affinity. The user may filter to any
N of their topics; unselected topics are simply excluded from the plan. Their slates are
retained, not discarded.

### No aggregation at request time

The feed query reads **precomputed columns only**. No `COUNT(*)` over engagement, no window
functions over event history. `card_quality` and `topic_affinity` are maintained by batch
jobs ([ADR-0011](0011-engagement.md)).

This is what keeps the read path under 100ms with no cache layer, and it is why Redis is not
needed yet.

## Consequences

**Easier**
- The difficulty mix is exact and testable rather than emergent.
- Progression is un-gameable by construction.
- The read path touches no aggregates, so it stays fast without a cache.

**Harder**
- Seen-state is now three states plus a cycle counter, and is dual-written (table + bitmap)
  with a reconciliation job.
- Slates and plans are server-side state with TTLs and invalidation rules, and there are now
  N slates per user rather than one.
- Deferred-card cycling is genuinely fiddly and needs real test coverage. A bug here shows
  as "I keep seeing the same cards", which is the most damaging feed bug there is.

**Committed to**
- Composition rules (mix, diversity) never live in the ranker.
- Ranking weights and the exploration rate are config, not code.
- The bitmap is always rebuildable from the table.

## Alternatives considered

**Bitmap only, no table.** Rejected: loses analytics and debuggability, and forces early
answers on ordinal semantics that interact badly with card versioning.

**Table only, no bitmap.** Simplest and correct, and the anti-join is affordable today.
Rejected because the derived bitmap costs little given the bounded corpus and removes the
feed query's most expensive component permanently.

**Difficulty mix as a ranking weight.** Rejected: approximate, drifting, untestable.

**One combined slate across all topics.** Simpler state (one row, one position), and
rejected: it forces cross-topic score comparison, which requires normalization we would
likely get subtly wrong; it handles per-topic difficulty tiers awkwardly; and every filter
change would invalidate the whole ranked slate, causing repeats or skips.

**Learned ranking (ML).** Rejected at this scale. There is no training data, no way to debug
a bad ranking, and a linear model with tunable weights is more useful until there is real
volume.

**Dwell only, no explicit control.** Rejected: an arbitrary threshold penalises fast readers,
and it gives no way for a user to say "I've got this".

**Explicit "Got it" only, no dwell fallback.** Rejected: ~250 deliberate taps per tier. Users
forget, and stalled progress for people who genuinely read everything is indistinguishable
from a broken gate.

**Treating explicit and dwell completion as the same signal.** Rejected for ranking purposes.
They both satisfy the progression gate, but an explicit tap is strong evidence of
comprehension while dwell only means a tab was open. Merging them discards that permanently —
and unlike most mistakes it is not recoverable from the event log if never recorded.

## Revisit when

- Expansion rate proves too low for the 80% gate to be reachable — then either the gate or
  the SEEN definition needs adjusting, informed by data rather than argument.
- The anti-join or slate computation shows up in latency measurements.
- There is enough engagement data that a learned ranker could beat tuned weights.
