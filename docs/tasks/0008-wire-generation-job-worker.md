# Task 0008: Wire `apps/worker` to the generation pipeline

**Owner:** unassigned

**Depends on:** [0009](0009-batched-topic-matching.md) (batched matching decides which
claimed topics actually need generation) and [0010](0010-one-shot-pipeline-redesign.md)
(the pipeline this task calls needs to already produce cards + questions per ADR-0026).
Can be scoped/designed in parallel with those, but shouldn't land before them.

**Background reading:**
[ADR-0026](../adr/0026-one-shot-generation-to-completion.md) (the execution model this
task implements), [generation-pipeline.md](../architecture/generation-pipeline.md).

## The problem

`generation/pipeline.py` (`run_generation_pipeline`) is built, tested, and runnable —
but the only thing that calls it today is `python -m spoin.generate_topics`, a manual
CLI. `apps/worker/src/spoin/worker/__main__.py` still claims pending `GenerationJob` rows
and then does nothing with them (`run_once()` logs a warning and leaves them `pending`) —
the production trigger (cron-dispatched worker claims a job, runs the pipeline, records
the result) doesn't exist.

## Why it matters

Nothing upstream of the CLI creates `GenerationJob` rows either (no demand-driven fill,
no admin trigger) — but even once something does, there's no handler to pick them up.
Without this, the corpus can only ever grow by someone manually running the CLI.

## What to do — per ADR-0026's execution model

- `GenerationJob` simplifies: it's "run the one-shot pipeline for this `topic_id`," full
  stop — `kind` and the old `subtopic_id` coalescing lock stop being load-bearing (see
  ADR-0026's "`GenerationJob` simplifies" section). Write the schema migration: drop or
  stop reading `kind`, change the coalescing key to `topic_id`.
- In `run_once()`, after selecting pending jobs, mark them `running` in the same
  transaction (so a crash mid-pipeline doesn't leave them silently re-claimable).
- **Cross-job concurrency and failure isolation happen at the worker level, not inside
  one `run_generation_pipeline` call** (ADR-0026): fire one `asyncio` task per claimed
  job, each opening its own `session_scope()`, gathered with per-task exception handling.
  One job's failure must not affect any other job's outcome or status.
- Each task: look up the job's `Topic` for `name`/`description`, build a single-item
  `topic_requests` list, call `run_generation_pipeline(session, generator, embedder,
  settings, topic_requests=[...])` inside that task's own session.
- Write back `status` (`completed`/`failed`), `completed_at`, `last_error`, and increment
  `attempts` from the pipeline's report or the caught exception — this is what makes the
  job queue's bookkeeping mean anything; right now nothing writes back to the job row at
  all.
- A completed job is terminal — per ADR-0026, no new `GenerationJob` is ever created for
  a `topic_id` that already has one completed. (Nothing currently creates jobs at all;
  this is a note for whoever builds that trigger later, not something to enforce here.)

## Hand back

`worker/__main__.py` actually processing claimed jobs concurrently with per-job isolation:
pipeline invoked once per job on its own session, job status written back accurately, and
`docker compose --profile worker up` demonstrably fills a topic's corpus (cards +
questions) from a `GenerationJob` row rather than the CLI.

## Timebox

Not started. Depends on 0009/0010 landing first. Rough guess once unblocked: half a day —
the hard part (the pipeline itself) is done elsewhere; this is wiring, the schema
migration, and the per-job `asyncio` fan-out.
