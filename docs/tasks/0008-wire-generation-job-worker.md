# Task 0008: Wire `apps/worker` to the generation pipeline

**Owner:** unassigned

## The problem

`generation/pipeline.py` (`run_generation_pipeline`) is built, tested, and runnable —
see [`docs/architecture/generation-pipeline.md`](../architecture/generation-pipeline.md).
But the only thing that calls it today is `python -m slocho.generate_topics`, a manual
CLI. `apps/worker/src/slocho/worker/__main__.py` still claims pending `GenerationJob`
rows and then does nothing with them (`run_once()` logs a warning and leaves them
`pending`) — the production trigger (cron-dispatched worker claims a job, runs the
pipeline, records the result) doesn't exist.

## Why it matters

Nothing upstream of the CLI creates `GenerationJob` rows either (no demand-driven fill,
no admin trigger) — but even once something does, there's no handler to pick them up.
Without this, the corpus can only ever grow by someone manually running the CLI.

## What to do

- Implement job handling in `worker/__main__.py`'s `run_once()`: for each claimed
  `GenerationJob`, build a `TopicRequest` from it and call
  `run_generation_pipeline(session, generator, embedder, settings, topic_requests=[...])`,
  inside the worker's own `session_scope()`.
- Decide how a `GenerationJob` (today: `kind`, `topic_id`, `subtopic_id`, `priority`)
  maps onto `run_generation_pipeline`'s `topic_requests` — a job's `kind` is currently
  `curriculum | cards | questions`, but the pipeline doesn't distinguish those; it always
  does curriculum-if-needed-then-cards for whatever topic it's given. Reconcile this: either
  collapse job `kind` down to "generate this topic" (simplest, matches what the pipeline
  actually does), or extend the pipeline to honor a job that only wants a top-up pass on
  an already-curriculum'd topic's specific subtopic.
- Set `GenerationJob.status`/`completed_at`/`last_error`/`attempts` from the pipeline's
  report (`accepted`/`rejected` counts, or an exception) — this is what makes the
  coalescing lock and priority queue (ADR-0006, ADR-0007's amendment) actually mean
  anything; right now nothing writes back to the job row at all.
- Decide whether one worker pass handles one job or several — `settings.generation_batch_size`
  worth of jobs are already claimed per pass (`run_once`'s `.limit(settings.generation_batch_size)`),
  but they're currently claimed and ignored. Running several jobs in one
  `run_generation_pipeline(topic_requests=[...])` call is possible today (the pipeline
  already fans out per topic) — decide if that's the right batching unit or if each job
  should get its own pipeline invocation.

## Hand back

`worker/__main__.py` actually processing claimed jobs: pipeline invoked, job status
written back, `docker compose --profile worker up` demonstrably fills a topic's corpus
from a `GenerationJob` row rather than the CLI.

## Timebox

Not started. Rough guess: half a day — the hard part (the pipeline itself) is done;
this is wiring plus the `kind`-to-`topic_requests` reconciliation above.
