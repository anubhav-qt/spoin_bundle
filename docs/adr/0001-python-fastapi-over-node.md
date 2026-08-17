# ADR-0001: Python + FastAPI for the API and workers

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav

## Context

Slocho needs a backend that serves a web client now and a React Native client later,
plus background workers doing substantial LLM orchestration.

Two forces pointed in opposite directions:

1. **Type sharing.** A TypeScript backend (NestJS/Fastify) shares types with the
   Next.js frontend directly, and lets one language cover the whole stack.
2. **LLM ecosystem and team proficiency.** The LLM tooling ecosystem's center of
   gravity is Python — LangChain's JS port lags the Python one in integrations,
   documentation, and feature parity. Separately, Anubhav is substantially more
   proficient in Python, and this is a two-person project where velocity is bounded
   by the people, not the runtime.

An initial recommendation of Node/NestJS was made and then reversed once proficiency
and ecosystem maturity were weighted correctly.

## Decision

**The API and workers are Python: FastAPI + Pydantic v2, async throughout.**
The web frontend remains TypeScript (Next.js) and consumes the API over HTTP.

The lost type-sharing is recovered by **generating** TypeScript types from FastAPI's
auto-produced OpenAPI schema:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o packages/api-types/schema.d.ts
```

This runs in CI. A Pydantic model change that breaks the frontend fails the build.

## Consequences

**Easier**

- The most complex part of the system (LLM orchestration) is written in the language
  with the best tooling for it, by the person most fluent in it.
- FastAPI's `/docs` gives interactive API documentation for free — a real
  developer-experience win we get without effort.
- Async-native fits the workload, which is IO-bound on LLM and DB calls.

**Harder**

- Two languages in the repo: two dependency managers, two lint/format toolchains,
  two CI job families.
- The API contract is now a generated artifact. If codegen is not wired into CI on
  day one, frontend/backend drift becomes silent. **This is the main risk of this ADR.**

**Committed to**

- The contract between web and API is the OpenAPI schema. It is generated from the
  serving code, never hand-maintained.

## Alternatives considered

**Node + NestJS everywhere.** Would have given native type sharing and one language.
Lost because it puts the hardest subsystem on the lagging LangChain port and outside
the team's strongest language — paying a permanent velocity tax to avoid a codegen step.

**Polyglot: Node API + Python LLM microservice.** What a large org would likely do.
Rejected hardest of the three. For two people it is the worst option available: two
dependency systems, two deploy pipelines, two auth implementations, and an internal
service boundary that must be versioned — all to serve a scale that does not exist yet.

## Revisit when

- Frontend/backend contract drift causes a production bug despite CI codegen, or
- LangChain JS reaches parity _and_ the team's TS proficiency exceeds its Python
  proficiency (unlikely), or
- Python's performance becomes a measured bottleneck — note that at any plausible
  scale here the bottleneck will be Postgres and the LLM provider, not the runtime.
