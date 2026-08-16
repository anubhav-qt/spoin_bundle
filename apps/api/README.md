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

- Content generation. That's `apps/worker` (same code, different entrypoint).
- Rendering or client state. That's `apps/web`.

## Layout

```
src/slocho/
  core/         config, database session
  domain/       enums, SQLAlchemy models — the schema everything inherits
  api/          FastAPI app, routers, wire schemas
  feed/         the read path: strata, ranking, interleave, service
  engagement/   event ingest and the seen-state machine
  generation/   ContentGenerator — the ONLY place LangChain may be imported
  embeddings/   local embedders; never a quota'd API
  worker/       batch job entrypoint
  fixtures/     the pre-generated card corpus used by `make seed`
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
pip install -e ".[dev]" && alembic upgrade head && python -m slocho.seed
```

## Optional extras

Both are excluded from the default install on purpose.

- `.[embeddings]` — `fastembed` / BGE-small. Without it, `SLOCHO_EMBEDDER=hash`
  gives a deterministic stand-in that keeps the image small and the tests fast.
  It is **not semantically meaningful**; install this before trusting any
  similarity number.
- `.[generation]` — LangChain. Keeping it optional makes ADR-0002's boundary
  physical: an import outside `generation/langchain_impl.py` fails to resolve in a
  default install, before the CI lint rule even has to catch it.

## Status

Foundation and the feed read path are implemented. Generation workers, the quality
gate and quizzes are scaffolded but not built — see the repo README's roadmap.
