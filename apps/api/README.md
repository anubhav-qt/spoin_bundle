# apps/api

FastAPI service. **The single source of truth for all clients** — the web app today, the
React Native app later. Both talk to it over HTTP with no privileged access.

> If the web client can do something the mobile client can't, that's a bug.

## Owns

- All business logic. None of it lives in `apps/web`.
- The OpenAPI schema, from which `packages/api-types` is generated.
- Auth verification, rate limiting, the quota governor.
- Feed serving: candidate generation, seen-filtering, difficulty mixing, pagination.
  **No LLM call may appear anywhere in this path.**
- Quiz serving and grading.

## Does not own

- Content generation. That's `apps/worker`.
- Rendering or client state. That's `apps/web`.

## Start reading

`src/` module layout, then the feed service — it's where the architecture's constraints
are most visible.

Interactive API docs at `/docs` once running.

## Status

Not yet implemented. See [`docs/architecture/overview.md`](../../docs/architecture/overview.md).
