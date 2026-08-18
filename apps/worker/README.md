# apps/worker

Background jobs. Shares the codebase and models with `apps/api`; different entrypoint.

Everything slow, async, and quota-bound lives here. Nothing here is ever in a user-facing
request path.

## Owns

- **Curriculum pass** — one call per topic, produces subtopics and `deep_dive` edges.
- **Card generation** — batched, targeted at a subtopic, sequential within a subtopic and
  parallel across them.
- **Topic canonicalization** — local embeddings, banded matching, LLM judge for the
  middle band.
- **Question bank generation** — questions derived from cards. Not built.
- **Quality gate** — dedup, topic conformance, difficulty, factual accuracy. Not built
  (only structural validation exists today).

The first three are implemented in `generation/pipeline.py` (a LangGraph graph — see
[generation-pipeline.md](../../docs/architecture/generation-pipeline.md)), and this
package's own entrypoint (`worker/__main__.py`) claims pending `GenerationJob` rows and
runs it — see task [0008](../../docs/tasks/0008-wire-generation-job-worker.md), closed.
`python -m spoin.generate_topics` still exists as a direct CLI path that bypasses the
job queue entirely (useful for one-off scripted runs), but the app's own "type a topic
in the UI" path now goes through `GenerationJob` end to end.

## How it runs

v1 runs as a **scheduled batch job** (GitHub Actions cron, ~15 min), not a persistent
worker pool. At free-tier quota there is nothing for a persistent pool to do 99% of the
time, and free hosting tiers sleep idle services anyway.

The same job functions run as a persistent loop once we're paying. Different entrypoint,
same code. See [ADR-0003](../../docs/adr/0003-free-tier-first.md).

**Local dev is the one place a persistent loop already exists**, `python -m spoin.worker
--watch` — `docker-compose.yml`'s `worker` service runs this by default, polling for
pending jobs every few seconds so a topic typed into the app locally actually gets
generated without manually rerunning the worker. `--watch` is dev ergonomics on top of
the exact same `run_once()`/`_run_job` code the cron entrypoint calls, not a change to
the production shape above.

## Local GPU

Seeded topics can be generated locally on an RTX 5070 via a `LocalContentGenerator`, with
cloud verification. The GPU is **never** a serving dependency.
See [ADR-0008](../../docs/adr/0008-local-gpu-generation.md).

## Status

The generation logic this package is meant to run exists and is tested
(`generation/pipeline.py`), and this package's own entrypoint (job claiming, calling
that pipeline, writing results back to `GenerationJob`) is implemented — task
[0008](../../docs/tasks/0008-wire-generation-job-worker.md), closed.
