# ADR-0073: The worker runs generation jobs one at a time

- **Status:** Superseded by [ADR-0078](0078-topic-parallel-key-leases.md)
- **Date:** 2026-08-30
- **Deciders:** Anubhav

> **Superseded by [ADR-0078](0078-topic-parallel-key-leases.md) (2026-09-01).**
> The owner asked for topic-level parallelism against a 100+ key pool. The worker
> again runs its admitted jobs concurrently (`asyncio.gather`, the pre-this-ADR
> shape), with a key-budget admission step in front: a topic is admitted while
> `sum(N keys) <= pool_size`, where `N` is its widest difficulty tier. Per-job
> session isolation and the quota-requeue path below are unchanged. The
> "Alternatives considered" here (bounded pool, one-job-per-pass) informed
> ADR-0078's packer.
- **Amends:** the "per-job isolation" note in
  [`apps/api/src/spoin/worker/__main__.py`](../../apps/api/src/spoin/worker/__main__.py)
  and the concurrency implied by [ADR-0026](0026-one-shot-generation-to-completion.md) (one-shot
  pipeline) — the pipeline stays one-shot and idempotent; only how many run at
  once changes. Does not touch [ADR-0024](0024-langgraph-for-card-generation-pipeline.md), which
  governs concurrency *within* a single topic's run.

## Context

`run_once()` claimed a batch of pending `GenerationJob` rows
(`generation_batch_size`, default 10) and ran them **concurrently** —
`asyncio.gather(*(_run_job(...) for ...))`, each job on its own DB session with
per-job failure isolation. The batched topic-request endpoint
(`POST /topics/batch`, task 0032) enqueues one job per new topic, so a user
adding several custom topics at once had them all generating in parallel in the
next worker pass.

The owner wants topics added from the app to generate **in the order they were
requested, one finishing before the next starts** — a sequential queue, visible
as the `GenerationProgressPanel`s completing in order rather than all creeping
forward together.

The concurrency was never load-bearing: `max_concurrent_generation_calls`
(default 5) already bounds in-flight LLM calls across a pass, and the quota
governor (ADR-0028/0065) spreads them across keys. Removing cross-job
concurrency changes throughput and ordering, not correctness or provider safety.

## Decision

**`run_once()` runs claimed jobs sequentially, in claim order**
(`ORDER BY priority DESC, created_at`):

```python
for job_id, topic_id in claimed:
    await _run_job(job_id, topic_id, generator, embedder)
```

The claim step is unchanged — a pass still takes up to `generation_batch_size`
rows under `FOR UPDATE SKIP LOCKED`. Each job still runs on its own session with
its own try/except; `_run_job` swallows its exceptions, so a failed job just
advances the loop. `run_generation_pipeline` is already idempotent (ADR-0026),
so a job requeued on quota exhaustion resumes cleanly on a later pass.

## Consequences

**Easier**

- Topics finish in request order. The whole batch a user adds generates one
  after another, matching what they see in the progress panels.
- One topic's run has the pass's resources to itself — no interleaving of two
  topics' pipeline calls, DB sessions or log lines. A stalled run blocks the
  ones behind it in the same pass rather than racing them.
- Simpler failure reasoning: at most one job is `running` at a time.

**Harder**

- **Throughput drops.** A pass that finished 10 topics in ~T now takes ~10 × T.
  On the production ~15-minute cron, a burst of new topics can outrun a single
  pass and spill into later passes; the queue drains slower. Acceptable at
  free-tier volume (generation is rare and quota-bound anyway), and revisited
  if the backlog becomes real.
- A single very slow or hung job now delays every job behind it in the pass,
  where before it only delayed itself. The per-attempt timeout (ADR-0056) still
  bounds any one call; a whole run has no hard ceiling.

**Committed to**

- Cross-job concurrency does not come back without a new decision here. If
  throughput becomes the binding constraint, the answer is a bounded worker
  pool (e.g. 2–3) or more frequent passes, chosen deliberately — not a silent
  return to unbounded `gather`.

## Alternatives considered

**Keep `gather`, cap it with `asyncio.Semaphore(N)`.** A bounded pool — most of
the throughput, still roughly in-order at low N. Rejected for now: the owner
asked for strictly sequential, and the pool size would be another tuning knob to
justify. This is the natural first step back if sequential proves too slow.

**Claim one job per pass (`generation_batch_size = 1` for the worker).** Forces
sequentiality by starving the pass. Rejected: it couples the claim limit to the
concurrency decision, wastes pass capacity when there's time to do more, and
multiplies claim-transaction overhead. Claiming a batch and working it in order
is strictly better.

**Only serialise jobs from the same batch request.** Track a batch id and run
those in order while letting unrelated topics run in parallel. Rejected as
premature: it needs a new column and a grouping pass for a distinction nobody
has asked to preserve, and "everything is sequential" is the simplest thing that
delivers what was asked.

## Revisit when

- The generation backlog visibly lags — new topics routinely wait more than a
  pass or two. Then move to a small bounded pool (the first alternative above),
  sized to observed pass duration, not back to unbounded.
- The worker becomes a paid persistent loop rather than a cron one-shot. At that
  point continuous throughput matters and the pool question is worth reopening
  with real numbers.
