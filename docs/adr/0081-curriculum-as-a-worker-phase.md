# ADR-0081: Curriculum runs as a worker phase, before key-budget admission

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Anubhav
- **Amends:** [ADR-0078](0078-topic-parallel-key-leases.md) -- the key-budget
  admission step now sees a real `topic_tier_width` for a fresh topic instead of
  the provisional `default_topic_key_budget`. The provisional path stays as a
  fallback, not the common case.

## Context

ADR-0078 admits pending jobs while `sum(N) <= pool_size`, where `N` is a topic's
widest difficulty tier (`persistence.topic_tier_width`). But a brand-new topic
has no curriculum at admission time, so `N` is unknown and the worker uses
`settings.default_topic_key_budget` (8).

Live failure this produced: seven fresh topics were each admitted at budget 8
(7 x 8 = 56 <= 119), then each ran its curriculum inside the pipeline and
discovered a real widest tier of ~34-46. `resolve_and_plan_topic` then called
`lease_topic_keys(~40)` against a pool that was already committed ~2.5x over --
so most topics got a partial or zero lease and fell back to the whole-pool scan.
~45 subtopic-group branches then contended for 119 keys with no lease isolation,
which drove a 429 storm (~350 `(key, model)` cells hit provider rate limits, a
chunk of them classified per-day and pinned). ADR-0078's own "Revisit when"
named exactly this: *"Fresh topics routinely fall back to the whole-pool scan.
The provisional budget is too far from real widths -- ... split curriculum into
its own worker pass so `N` is always known at admission."*

## Decision

**`run_once` gets a curriculum phase between claiming and admitting.**

1. **Claim.** Select pending jobs (`priority DESC, created_at`), `FOR UPDATE`,
   and mark them `running` -- so an overlapping pass cannot re-dispatch them
   while the curriculum phase runs.
2. **Curriculum.** `_ensure_curricula` generates and commits a curriculum for
   every claimed non-repair topic that lacks one, bounded by
   `settings.curriculum_concurrency` (4) -- one thinking-pool call per topic. A
   per-topic failure (quota, malformed response) is logged and left.
3. **Admit.** `_admit_by_key_budget` re-reads the claimed jobs in claim order;
   `topic_tier_width` now returns a real number for the topics whose curriculum
   just landed. Jobs that don't fit are demoted back to `pending` for the next
   pass (they were only `running` to hold them through phase 2).
4. **Dispatch** the admitted set, unchanged (ADR-0078).

The curriculum-generate-and-persist logic is extracted from
`resolve_and_plan_topic` into `persistence.ensure_curriculum(session, generator,
settings, topic)` -- idempotent (no-ops when `curriculum_generated_at` is set),
commits its own work. `resolve_and_plan_topic` still calls it inline, so a topic
that reaches the pipeline without a curriculum (a direct `generate_topics.py`
run, a curriculum-phase quota exhaustion) still works exactly as before.

## Consequences

**Easier**

- Fresh topics get a real key lease on their first pass. The provisional-budget
  over-admit is now the exception (a topic whose curriculum phase failed), not
  the norm for every new topic.
- `sum(N)` at admission is accurate, so `sum(N) <= pool_size` actually bounds
  concurrency the way ADR-0078 intended -- which is the upstream fix for the
  lease-starvation 429 storm.

**Harder**

- A pass now front-loads curriculum generation (one thinking call per fresh
  topic, 4-wide) before any card work -- roughly 1-3 minutes for a batch of new
  topics.
- Claimed jobs sit `running` through the curriculum phase. A worker killed
  mid-phase leaves them stuck `running` -- the same class of gap `_run_job`
  already notes, but the window grew from milliseconds to the phase's duration.
  A stale-`running` sweep is still unbuilt.
- Curriculum-phase quota exhaustion for a topic is survivable but buys nothing
  that pass: it admits at the provisional budget and `resolve_and_plan_topic`
  generates the curriculum inline -- the pre-ADR-0081 behaviour.

## Alternatives considered

**A `kind='curriculum'` job** (like ADR-0076's repair kind): the topic-request
flow enqueues a curriculum job, the worker runs those first, and completion
enqueues the generation job. Cleaner cross-pass separation. Rejected as more
surface -- two job rows per topic, a new priority rule -- for the same outcome;
the phase is fully contained in `run_once`.

**Keep curriculum inline, just cap topics-per-pass low when widths are unknown.**
A 2-topic cap still over-admits if both are wide and under-admits when they're
narrow. Knowing the real number beats guessing conservatively.

## Revisit when

- The curriculum phase's front-loading latency becomes the pass's bottleneck --
  raise `curriculum_concurrency`, or move to the `kind='curriculum'` job so
  curricula are done in an earlier pass entirely.
- Stuck-`running` rows from mid-phase crashes become an operational problem --
  build the stale-claim sweep (`status='running'` older than N minutes ->
  `pending`).
