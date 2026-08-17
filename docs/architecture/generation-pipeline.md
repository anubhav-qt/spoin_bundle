# Generation pipeline — how the corpus gets filled

> Prerequisite: [`overview.md`](overview.md) and [`content-model.md`](content-model.md).
> This document is the implementation-level companion to
> [ADR-0007](../adr/0007-curriculum-driven-generation.md) (curriculum-driven generation),
> [ADR-0024](../adr/0024-langgraph-for-card-generation-pipeline.md) (why LangGraph, and what
> it does and doesn't own), and [ADR-0004](../adr/0004-topic-canonicalization.md) (topic
> merging). Read those for *why*; this doc is *what exists and how to run it*.

> **A redesign is decided but not yet built.**
> [ADR-0025](../adr/0025-batched-llm-topic-matching.md) replaces the topic-matching
> logic below with a batched LLM call, and
> [ADR-0026](../adr/0026-one-shot-generation-to-completion.md) adds a questions node,
> threads linked-difficulty-tier content forward, and moves cross-topic concurrency to
> the worker. Everything below still describes what's actually in the code today — see
> tasks [0009](../tasks/0009-batched-topic-matching.md) and
> [0010](../tasks/0010-one-shot-pipeline-redesign.md) for the pending implementation.

## What's actually built

The generation logic — curriculum planning, topic resolution/merging, card generation,
the minimal gate — is built, tested, and runnable today. What's **not** built is the
production trigger: nothing yet creates a `GenerationJob` row or calls this from
`apps/worker`. The only way to run it today is the CLI:

```bash
python -m spoin.generate_topics "Topic Name" "Another Topic::with a description"
```

This calls `generation.pipeline.run_generation_pipeline(...)` directly, synchronously,
inside one DB transaction — exactly the function signature a future
`GenerationJob` handler in `apps/worker` will call. See "What's missing" below.

## The graph

`generation/pipeline.py` is a [LangGraph](https://github.com/langchain-ai/langgraph) graph
— the only module in the codebase allowed to import `langgraph`
(ADR-0024, enforced by `tests/test_architecture.py` and a ruff banned-api rule, the same
mechanism ADR-0002 uses for `langchain*`).

```
START
  |  Send fan-out, one branch per requested topic (independent — a topic
  |  that's already curriculum'd and just topping up cards never waits on
  |  a sibling topic still doing its first curriculum pass)
  v
resolve_and_plan_topic
  - embed the topic name, cosine-search existing Topic rows (pgvector)
  - band decision (ADR-0004): auto-merge / mid-band LLM judge / new topic
  - if curriculum_generated_at is unset: one generate_curriculum() call,
    persist Subtopic rows (grouped across difficulty tiers via
    subtopic_group_id — the model decides which tiers a concept needs,
    never a mechanical beginner+intermediate+advanced grid)
  - if already curriculum'd: skip straight to loading existing subtopics
  |
  | Send fan-out, one branch per subtopic this topic still needs cards for
  v
generate_subtopic_cards
  - no DB access (concurrent across subtopics AND topics)
  - sequential batches within one subtopic (ADR-0007: each call sees
    what the last one produced), parallel across subtopics
  |
  | fan-in (every branch's results merge, across every topic in the run)
  v
gate_and_persist
  - the ONLY card-writing node, one writer, no concurrency to reason about
  - minimal pass-through gate (generation/gate.py) — see "What's missing"
  - embeds body, derives archetype, bootstraps CardStats
```

Every real generator call (curriculum, topic-match judge, card generation) goes through
a shared `asyncio.Semaphore` (`SPOIN_MAX_CONCURRENT_GENERATION_CALLS`) — without it, a
run with several topics times many subtopics each would fire dozens of simultaneous
calls, well past `SPOIN_QUOTA_RPM`.

## Subtopic reuse: prevention, not detection

When a curriculum pass runs against a topic that already has some subtopics (an old
seed-fixture topic getting real curriculum for the first time, most commonly), the new
subtopics need to avoid forking near-duplicates of what's already there. The mechanism
is **exact-title prevention**, not a similarity/judge layer: existing subtopic titles are
handed to `generate_curriculum` as `existing_subtopics` context, with the instruction to
reuse an exact title verbatim when it already covers a concept the model was about to
propose. Persistence then just does an exact `(topic_id, title, difficulty)` lookup.

This is the same pattern already used for card titles (`generate_cards`'s
`existing_titles`) — deliberately. An earlier version of this added a second
embedding-column + LLM-judge layer purely for subtopic reconciliation, mirroring
ADR-0004's topic-canonicalization machinery one level down. It was removed: subtopics are
reconciled once per topic (not repeatedly, at volume, the way cards are), so the
detection-layer complexity ADR-0007 accepts for cards wasn't earning its cost here. The
curriculum call already has full context to make this a single "taste" decision in the
same request, the same trust level as everything else in that call.

## Two generator backends

`SPOIN_GENERATOR` selects which `ContentGenerator` implementation
`generation.get_content_generator()` returns:

- **`fake`** (default, everywhere except a deliberate switch) — `generation/fake.py`.
  Deterministic, in-memory, no network, no quota. This is what every automated test and
  the CLI examples above run against.
- **`gemini`** — `generation/langchain_impl.py`. The only module allowed to import
  `langchain*` (ADR-0002/0024). Requires `SPOIN_GEMINI_API_KEYS` (comma-separated); raises
  a clear config error at construction if unset, rather than failing mid-run.
  **Not live-verified** — built and covered by mocked unit tests
  (`tests/test_langchain_impl.py`: structured-output parsing, per-item validation,
  partial-failure handling), but no real Gemini key has been used to confirm prompt
  *quality*. Treat the prompts in that file as a first draft.
- **`local`** — not implemented (ADR-0008).

Switching backends is a `.env` change only; nothing else in the pipeline knows or cares
which one is behind the interface.

### Quota governance

`generation/quota.py`'s `QuotaGovernor` rotates through `SPOIN_GEMINI_API_KEYS`,
tracking spend per key per day in the existing `QuotaLedger` table
(`backend=f"gemini:{key_index}"`, `exhausted_at` set the moment a key hits
`SPOIN_QUOTA_DAILY_REQUESTS` for the day). It opens its own short-lived DB session per
call rather than sharing the pipeline's — the pipeline's session is deliberately
single-writer/lock-guarded (see ADR-0024's "Harder" section), and quota bookkeeping has
no reason to be tied to that transaction. Tested standalone
(`tests/test_quota_governor.py`); **not wired to anything yet**, since it's only
meaningful once real Gemini calls exist to wrap — `langchain_impl.py` calls it before
every actual API call.

## What's missing

- **Worker/`GenerationJob` wiring.** The CLI is the only trigger. See task
  [0008](../tasks/0008-wire-generation-job-worker.md).
- **The real quality gate.** `generation/gate.py` is structural validation only (non-empty
  body). Near-duplicate detection, topic conformance, and the independent
  difficulty/factual-accuracy judge (content-model.md's "Quality gate" section) are
  unbuilt — every card that reaches `gate_and_persist` becomes `active` immediately.
- **The ASCII scene catalog** (ADR-0021). `CardDraft.visual_id`/`visual_slots` exist in
  the schema and the interface, but there's no catalog for a generator to select from, so
  nothing populates them in practice yet.
- **Live Gemini verification.** See above.
