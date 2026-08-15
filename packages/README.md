# packages/

Shared code and generated contracts.

## `api-types/`

TypeScript types **generated** from the API's OpenAPI schema. Not hand-maintained, and
gitignored — CI regenerates them and fails the build on drift.

This is how a Python backend and a TypeScript frontend stay type-safe across the language
boundary. See [ADR-0001](../docs/adr/0001-python-fastapi-over-node.md).

---

Anything added here must be genuinely shared. A package with one consumer belongs in that
consumer.
