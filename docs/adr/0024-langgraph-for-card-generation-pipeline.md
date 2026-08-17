# ADR-0024: LangGraph for the card-generation pipeline, worker stays the scheduler

- **Status:** Accepted
- **Date:** 2026-08-17
- **Deciders:** Anubhav
- **Amends:** [ADR-0002](0002-langchain-behind-an-interface.md) ("LangGraph for generation
  flows" was deferred there, not rejected)

## Context

ADR-0002 drew a line: LangChain is composition, not orchestration. Parallelism and
durability come from the job queue (`GenerationJob` + the cron-triggered worker), never
from the LLM-composition library. It explicitly deferred LangGraph: _"if generation
becomes a genuinely stateful multi-step workflow ... revisit."_

Building the first vertical slice (curriculum pass → per-subtopic card generation →
quality gate → corpus) is exactly that multi-step workflow: one call that must run
before the rest, a fan-out across subtopics that must run in parallel, and per-subtopic
generation that must stay **sequential within itself** (ADR-0007: each prompt to one
subtopic needs to see what the previous call to that subtopic produced).

The team also wants to use LangGraph deliberately, as a real tool to learn, not just
where it's strictly necessary. That's a legitimate reason to prefer it over a hand-rolled
`asyncio.gather`, provided it doesn't quietly re-introduce the thing ADR-0002 ruled out:
an LLM-composition library holding scheduling or durability state that competes with the
job queue.

## Decision

**LangGraph owns the control flow _inside_ one job's execution. The worker and
`GenerationJob` own everything about _when_ and _in what order_ jobs run, unchanged.**

```
worker/__main__.py           external trigger (cron), claims GenerationJob rows,
                              priority, coalescing, quota pacing  <- UNCHANGED

generation/pipeline.py       ONE topic's curriculum -> cards -> gate -> persist,
                              expressed as a LangGraph graph                <- NEW
  plan_curriculum node          1 call, sequential
  generate_subtopic_cards node  fan-out via Send, parallel across subtopics,
                                 sequential batches within one subtopic (plain loop,
                                 not a graph cycle — see "Alternatives")
  gate_and_persist node         fan-in, sequential, single DB writer
```

A `generate_topic_pipeline()` job handler in the worker will call
`generation.pipeline.run_topic_pipeline(...)` the same way it would call any other
plain async function — the worker does not know or care that LangGraph is inside.

**Checkpointing is in-memory, not persisted.** A persisted checkpointer (SQLite/Postgres
backend) would let a graph resume across process restarts, which sounds like durability
— but ADR-0003 already rules out an always-on process, and cross-restart durability at
the _job_ granularity is what `GenerationJob.attempts`/`last_error` already do. Two
systems both claiming to own "did this actually complete" is the exact conflict ADR-0002
was written to prevent. If a worker pass dies mid-graph, the whole job is simply retried
from the top on the next cron tick — acceptable because curriculum/card generation is
idempotent-ish by construction (existing titles are re-read from the DB each time) and
cheap relative to quota, not because LangGraph gave us resumability.

**Import boundary, extended:** `langgraph` is confined to `generation/pipeline.py`,
enforced the same way ADR-0002 confines `langchain*` to `langchain_impl.py` — a ruff
banned-api rule, not convention. `pipeline.py` never imports `langchain*` directly; it
only calls the `ContentGenerator` interface, so the graph doesn't know or care whether
the generator behind it is Gemini, local, or fake.

## Consequences

**Easier**

- The fan-out/fan-in across subtopics (parallel across, sequential within) is expressed
  directly as a `Send`-based map-reduce instead of hand-rolled `asyncio.gather` plus
  manual bookkeeping of which results came from which subtopic.
- A natural extension point for the next real workflow shape this product needs:
  gate-fails-a-subtopic-below-`min_cards` → loop back and top up with another batch, which
  is a graph cycle LangGraph supports natively and a plain async pipeline would not.
- LangSmith tracing (ADR-0002's original justification for LangChain) extends naturally
  to graph runs.

**Harder**

- A second orchestration-shaped dependency in the codebase (job queue _and_ LangGraph),
  which makes "why isn't this a `GenerationJob`" a question a new contributor has to learn
  the answer to. This ADR is that answer; keep it linked from `pipeline.py`'s docstring.
- LangGraph's `Send` map-reduce forces per-branch node functions to be free of any shared,
  non-thread-safe resource — concretely, `generate_subtopic_cards` cannot touch the
  `AsyncSession` (SQLAlchemy sessions aren't safe for concurrent task access), so all DB
  reads it would want (existing titles for top-up) must be pre-fetched in `plan_curriculum`
  and threaded through as plain data. A real constraint, not a style preference — get it
  wrong and cards silently get written by a corrupted session.
- One more library with API-churn risk (LangGraph is younger than LangChain core).

**Committed to**

- `pipeline.py` is the only place `langgraph` is imported.
- No persisted checkpointer. If that changes, it needs its own ADR — it would mean
  LangGraph is doing durability, and ADR-0002/ADR-0003's reasoning needs to be revisited,
  not silently invalidated.
- The worker/`GenerationJob` remains the sole source of truth for scheduling, priority,
  coalescing, and cross-run retry. LangGraph never reaches into that table.

## Alternatives considered

**Plain `asyncio.gather` (no LangGraph), as the original vertical-slice plan assumed.**
Simpler, zero new dependency risk. Loses the map-reduce ergonomics and the natural home
for a future retry-cycle. Rejected because the team specifically wants LangGraph
experience here, and the workflow shape genuinely fits it — this isn't LangGraph for
its own sake.

**LangGraph replacing the worker/`GenerationJob` entirely** (considered and explicitly
rejected in conversation before this ADR was written). LangGraph has no answer for
"which of many competing subtopics gets today's scarce quota first," coalescing
concurrent misses on one starved subtopic, or running on a schedule without an always-on
process. Those are this product's free-tier survival mechanics (ADR-0003 §3/§6,
ADR-0006), not generic orchestration problems — conflating them would silently lose the
quota governor and the coalescing lock.

**Persisted LangGraph checkpointing as the durability story.** Rejected per the
"Committed to" section above: it would require an always-on or externally-persisted
store, fighting ADR-0003's free-tier constraint, and it would compete with
`GenerationJob` for the answer to "is this job done."

## Revisit when

- A real cross-subtopic retry/top-up cycle gets built — the natural next LangGraph
  feature to reach for, per the fan-out/fan-in structure this ADR sets up.
- LangGraph ships a breaking change costing more than a day to absorb (same bar ADR-0002
  sets for LangChain).
- The pipeline's node count or branching grows enough that "worker owns scheduling,
  LangGraph owns one job's control flow" stops being a clean line — e.g. if a single job
  genuinely needs to span more than one `GenerationJob` row's worth of work.
