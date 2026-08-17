# ADR-0002: LangChain is used, but confined behind `ContentGenerator`

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav

## Context

Card generation involves prompt construction, model invocation, structured output
parsing, validation, retry-on-failure, and embedding. LangChain covers this, and the
team wants to use it.

Two things needed clarifying before committing:

**1. LangChain is not an orchestrator.** An early framing was that "LangChain will
deploy 3 workers in parallel" for 3 custom topics. It will not. LangChain is an
in-process composition library — it has no scheduler, no durable state, no
retry-across-restart, and no distributed execution. If the process dies mid-chain,
the work is gone. Parallelism and durability come from the job queue, not LangChain.

| Concern                                                    | Layer             | Tool                       |
| ---------------------------------------------------------- | ----------------- | -------------------------- |
| Run N jobs in parallel, retry on failure, survive a deploy | **Orchestration** | `procrastinate` (ADR-0003) |
| Inside one job: prompt → call → parse → validate → embed   | **Composition**   | LangChain                  |

**2. LangChain is not obviously the right tool for this specific workload.** For
schema-constrained card generation, `google-genai` + Pydantic + `instructor` is close
to equivalent and simpler to debug. LangChain also has a well-earned reputation for
API churn across versions.

What it does genuinely buy us: provider abstraction, retry/fallback chains, and
**LangSmith tracing** — full visibility into every prompt, completion, token count,
latency, and failure. That last item is the difference between debugging prompts and
guessing at them, and on its own justifies the dependency.

## Decision

**Use LangChain, entirely behind our own `ContentGenerator` interface.**

```
src/generation/
  base.py          # ContentGenerator — our interface. Pydantic in, Pydantic out.
  langchain_impl.py # the ONLY module in the codebase that imports langchain
  fake.py          # deterministic in-memory impl for tests and local dev
```

**Nothing outside `src/generation/langchain_impl.py` may import `langchain`.**
Enforced by a lint rule in CI, not by convention.

The interface speaks in our own Pydantic models. LangChain types never cross the
boundary.

## Consequences

**Easier**

- LangSmith tracing across all generation, which is our primary debugging tool for
  prompt quality and cost attribution.
- A `FakeContentGenerator` means tests and local development never call a real model,
  never burn quota, and run in milliseconds.
- Swapping LangChain out later is a one-module rewrite, not a refactor.

**Harder**

- A layer of indirection over an already-abstracted library. Accepted deliberately:
  LangChain's abstractions are chosen for LangChain's needs, not ours.
- A dependency with a history of breaking changes. The interface is what contains
  the blast radius when that happens.

**Committed to**

- The orchestration/composition split. Requests to "make generation faster" are
  answered by worker concurrency, never by changing chain code.

## Alternatives considered

**Direct SDK + `instructor` + Pydantic, no LangChain.** Simpler, fewer dependencies,
more debuggable. Lost on tracing: we would have had to build cost and prompt
observability ourselves, and that observability is load-bearing given a hard quota
ceiling (ADR-0003).

**LangChain used freely throughout.** Rejected. It would put a fast-moving third-party
API in the type signatures of our own domain code, and make the "is this a LangChain
bug or our bug?" question unanswerable.

**LangGraph for generation flows.** Deferred, not rejected. If generation becomes a
genuinely stateful multi-step workflow (research → draft → critique → revise), revisit.
Today it is a single structured call and LangGraph would be overhead.

## Revisit when

- LangChain ships a breaking change that costs more than a day to absorb, or
- Generation becomes a multi-step stateful workflow (consider LangGraph, or Temporal
  if it needs durability _between_ steps), or
- LangSmith's free tier stops covering our trace volume and the tracing benefit no
  longer justifies the dependency.

**Update:** the "multi-step stateful workflow" condition above was hit by the first
vertical slice (curriculum → per-subtopic generation → gate) and revisited in
[ADR-0024](0024-langgraph-for-card-generation-pipeline.md). LangGraph is now used, but
scoped to _inside_ one job's execution — the worker/`GenerationJob` split this ADR
describes for orchestration vs. composition is unchanged; LangGraph lives entirely on
the composition side of that line, confined to `generation/pipeline.py` the same way
`langchain*` is confined to `langchain_impl.py`.
