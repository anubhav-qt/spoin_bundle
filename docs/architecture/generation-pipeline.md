# Generation pipeline — how the corpus gets filled

> Prerequisite: [`overview.md`](overview.md) and [`content-model.md`](content-model.md).
> This document is the implementation-level companion to
> [ADR-0025](../adr/0025-batched-llm-topic-matching.md) (topic matching),
> [ADR-0026](../adr/0026-one-shot-generation-to-completion.md) (the one-shot execution
> model), [ADR-0007](../adr/0007-curriculum-driven-generation.md) (curriculum-driven
> generation), and [ADR-0024](../adr/0024-langgraph-for-card-generation-pipeline.md) (why
> LangGraph, and what it does and doesn't own). Read those for *why*; this doc is *what
> exists and how to run it*.

## What's actually built

Everything below is built, tested (`tests/test_generation_pipeline.py`,
`tests/test_worker.py`, `tests/test_langchain_impl.py`), and runnable — including the
production trigger: `apps/worker` claims `GenerationJob` rows and runs them for real.
Nothing yet *creates* those rows (no demand-driven trigger, no admin/API endpoint) — the
CLI and a hand-inserted row are the only ways a job exists today.

```bash
python -m spoin.generate_topics "Topic Name" "Another Topic::with a description"
```

## Two phases, two transactions

`generation/pipeline.py` exposes two entrypoints, meant to be called in **separate**
`session_scope()` blocks (see the CLI, `generate_topics.py`, or the worker,
`worker/__main__.py`, for the pattern) — so a topic's identity survives even if its
generation later fails and gets retried:

```
match_and_create_topics()    ADR-0025. Cheap, no card generation. Embeds every incoming
                              topic, finds its top-N nearest existing topics (pgvector,
                              free), then ONE batched LLM call decides yes/no per topic
                              against its own candidates — no thresholds. A match just
                              gets aliased. A non-match gets a brand-new Topic row, with
                              NO curriculum yet.

run_generation_pipeline()    ADR-0026. Takes topic_ids that ALREADY exist. One-shot:
                              curriculum (if not already generated) -> cards, per
                              subtopic per difficulty tier -> questions, generated from
                              the cards just written. Idempotent per topic — calling it
                              again for an already-finished topic has nothing left to do.
```

The worker calls `run_generation_pipeline` with a single topic_id per `GenerationJob`,
each in its own `asyncio` task and its own DB session — see "Worker" below for why.

## The graph

`run_generation_pipeline`'s graph is a [LangGraph](https://github.com/langchain-ai/langgraph)
graph — the only module in the codebase allowed to import `langgraph`
(ADR-0024, enforced by `tests/test_architecture.py` and a ruff banned-api rule, the same
mechanism ADR-0002 uses for `langchain*`). Topic matching (above) runs entirely outside
this graph, in plain Python — nothing to fan out, it's a single batched call.

```
START
  |  Send fan-out, one branch per topic_id (independent — a topic already
  |  curriculum'd and just topping up cards never waits on a sibling topic
  |  still doing its first curriculum pass)
  v
resolve_and_plan_topic
  - the topic already exists (matching decided that upstream)
  - if curriculum_generated_at is unset: one generate_curriculum() call,
    persist Subtopic rows (grouped across difficulty tiers via
    subtopic_group_id — the model decides which tiers a concept needs,
    never a mechanical beginner+intermediate+advanced grid)
  - if already curriculum'd: skip straight to loading existing subtopics
  |
  | Send fan-out, one branch per subtopic GROUP (not per tier — see below)
  v
generate_subtopic_cards
  - no DB access (concurrent across groups AND topics)
  - tiers WITHIN one group run sequentially, lowest difficulty first: a
    linked higher tier's generate_cards() call receives the lower tier's
    actual card BODIES as `builds_on` context, so it can genuinely build on
    them rather than just avoid repeating titles. Groups with one tier (the
    common case) are unaffected — nothing to sequence.
  |
  | fan-in (every branch's results merge, across every topic in the run)
  v
gate_and_persist
  - the ONLY writer node. Persists cards (minimal gate, generation/gate.py —
    see "What's missing"), embeds body, derives archetype, bootstraps
    CardStats — same as before.
  - THEN: concurrently (asyncio.gather, same semaphore as every other
    generator call) generates questions FROM the cards just persisted, per
    subtopic/difficulty, and persists those too (Question rows). A topic's
    report isn't "done" until both cards and questions exist.
```

Every real generator call (curriculum, topic matching, card generation, question
generation) goes through a shared `asyncio.Semaphore` (`SPOIN_MAX_CONCURRENT_GENERATION_CALLS`)
— without it, a run with several topics times many subtopics each would fire dozens of
simultaneous calls, well past `SPOIN_QUOTA_RPM`.

## Worker: per-job isolation, not graph-level fan-out

`apps/worker`'s `run_once()` claims pending `GenerationJob` rows, marks them `running` in
that same transaction, then fires one `asyncio` task per job — **each with its own DB
session** — gathered together. One job's exception marks only that job `failed`; it never
touches any other job in the same pass (ADR-0026). This is a different concurrency layer
from the graph's own `Send` fan-out above: the graph still owns concurrency *within* one
topic's run (subtopics, tiers); the worker owns concurrency *across* jobs.

`run_generation_pipeline` still accepts a list of topic_ids (the CLI can hand it several
at once, sharing one session — fine for a manual run where isolation doesn't matter); the
worker just always calls it with a single-item list, once per job.

## Subtopic reuse: prevention, not detection

When a curriculum pass runs against a topic that already has some subtopics (a retry of
an earlier partial run, or an old seed-fixture topic getting real curriculum for the
first time), the new subtopics need to avoid forking near-duplicates of what's already
there. The mechanism is **exact-title prevention**, not a similarity/judge layer: existing
subtopic titles are handed to `generate_curriculum` as `existing_subtopics` context, with
the instruction to reuse an exact title verbatim when it already covers a concept the
model was about to propose. Persistence then just does an exact `(topic_id, title,
difficulty)` lookup.

This is the same pattern already used for card titles (`generate_cards`'s
`existing_titles`) — deliberately. An earlier version of this added a second
embedding-column + LLM-judge layer purely for subtopic reconciliation, mirroring
ADR-0025's topic-matching machinery one level down. It was removed: subtopics are
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
  partial-failure handling, the batched matching call), but no real Gemini key has been
  used to confirm prompt *quality*, and no model choice has actually been evaluated
  (ADR-0008's open question). Treat the prompts in that file as a first draft.
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

- **Anything that actually creates `GenerationJob` rows.** The worker processes them once
  they exist; nothing yet decides a new topic should be generated and inserts the row —
  that's a demand-signal or admin-trigger question, unbuilt.
- **The real quality gate.** `generation/gate.py` is structural validation only (non-empty
  body). Near-duplicate detection, topic conformance, and the independent
  difficulty/factual-accuracy judge (content-model.md's "Quality gate" section) are
  unbuilt — every card that reaches `gate_and_persist` becomes `active` immediately.
- **The ASCII scene catalog** (ADR-0021). `CardDraft.visual_id`/`visual_slots` exist in
  the schema and the interface, but there's no catalog for a generator to select from, so
  nothing populates them in practice yet.
- **Live Gemini verification, and the model-choice question itself.** See above.
