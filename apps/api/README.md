# apps/api

FastAPI service. **The single source of truth for all clients** — the web app today, the
React Native app later. Both talk to it over HTTP with no privileged access.

> If the web client can do something the mobile client can't, that's a bug.

This directory holds the whole Python codebase. `apps/worker` is a **different
entrypoint into this same package**, not a second project (ADR-0003 §2: moving from a
cron batch worker to a persistent pool must be a process-type change, not a rewrite).

## Owns

- All business logic. None of it lives in `apps/web`.
- The OpenAPI schema, from which `packages/api-types` is generated.
- Auth verification, rate limiting, the quota governor.
- Feed serving: candidate generation, seen-filtering, difficulty mixing, pagination.
  **No LLM call may appear anywhere in this path.**
- Quiz serving and grading.

## Does not own

- Triggering content generation on a schedule. That's `apps/worker` (same code, different
  entrypoint) — though as of now the generation logic itself (`generation/pipeline.py`)
  only runs via a CLI script (`generate_topics.py`), not the worker; see
  [generation-pipeline.md](../../docs/architecture/generation-pipeline.md) and task
  [0008](../../docs/tasks/0008-wire-generation-job-worker.md).
- Rendering or client state. That's `apps/web`.

## Layout

```
src/spoin/
  core/         config, database session
  domain/       enums, SQLAlchemy models — the schema everything inherits
  api/          FastAPI app, routers, wire schemas
  feed/         the read path: strata, ranking, interleave, service
  engagement/   event ingest and the seen-state machine
  generation/   ContentGenerator, the LangGraph pipeline, quota governor — the
                ONLY place LangChain/LangGraph may be imported (one file each)
  embeddings/   local embedders; never a quota'd API
  worker/       batch job entrypoint
  fixtures/     the pre-generated card corpus, loaded by `python -m spoin.seed` (manual, not run by default)
```

## Start reading

`feed/strata.py`, then `feed/service.py`. The architecture's constraints are most
visible there: the difficulty mix as a structural constraint rather than a ranking
weight, and the read path touching only precomputed columns.

Then `generation/base.py` for the boundary ADR-0002 draws, and
`domain/models/card.py` for the schema everything else inherits.

Interactive API docs at `/docs` once running.

## Running

Use the root `docker compose up` / `make dev`. Directly:

```bash
pip install -e ".[dev]" && alembic upgrade head
```

`spoin_db` (see root `CLAUDE.md`) starts and stays blank -- `python -m spoin.seed`
still works if you want the fixture corpus loaded on your own machine, but it's no
longer run by default and shouldn't be run against the shared dev database without
asking first.

## Optional extras

Both are excluded from the default install on purpose.

- `.[embeddings]` — `fastembed` / BGE-small. Without it, `SPOIN_EMBEDDER=hash`
  gives a deterministic stand-in that keeps the image small and the tests fast.
  It is **not semantically meaningful**; install this before trusting any
  similarity number.
- `.[generation]` — LangChain. Keeping it optional makes ADR-0002's boundary
  physical: an import outside `generation/langchain_impl.py` fails to resolve in a
  default install, before the CI lint rule even has to catch it.

## Status

Foundation and the feed read path are implemented. The generation pipeline (curriculum,
topic merging, card generation, both a `fake` and a real Gemini backend) is built and
tested — see [generation-pipeline.md](../../docs/architecture/generation-pipeline.md) —
but only runs via a CLI script today, not the worker/cron trigger. The real quality gate
and quizzes are still scaffolded, not built.
