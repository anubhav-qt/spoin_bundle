# Generation pipeline -- how the corpus gets filled

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
`tests/test_worker.py`, `tests/test_langchain_impl.py`), and runnable -- including the
production trigger: `apps/worker` claims `GenerationJob` rows and runs them for real.
Nothing yet *creates* those rows (no demand-driven trigger, no admin/API endpoint) -- the
CLI and a hand-inserted row are the only ways a job exists today.

```bash
python -m spoin.generate_topics "Topic Name" "Another Topic::with a description"
```

## Two phases, two transactions

`generation/pipeline/` exposes two entrypoints (re-exported from its `__init__`; see
[ADR-0044](../adr/0044-generation-pipeline-as-a-package.md)), meant to be called in **separate**
`session_scope()` blocks (see the CLI, `generate_topics.py`, or the worker,
`worker/__main__.py`, for the pattern) -- so a topic's identity survives even if its
generation later fails and gets retried:

```
match_and_create_topics()    ADR-0025. Cheap, no card generation. Embeds every incoming
                              topic, finds its top-N nearest existing topics (pgvector,
                              free), then ONE batched LLM call decides yes/no per topic
                              against its own candidates -- no thresholds. A match just
                              gets aliased. A non-match gets a brand-new Topic row, with
                              NO curriculum yet.

run_generation_pipeline()    ADR-0026. Takes topic_ids that ALREADY exist. One-shot:
                              curriculum (if not already generated) -> cards, per
                              subtopic per difficulty tier -> questions, generated from
                              the cards just written. Idempotent per topic -- calling it
                              again for an already-finished topic has nothing left to do.
```

The worker calls `run_generation_pipeline` with a single topic_id per `GenerationJob`,
each in its own `asyncio` task and its own DB session -- see "Worker" below for why.

## The graph

`run_generation_pipeline`'s graph is a [LangGraph](https://github.com/langchain-ai/langgraph)
graph -- the only module in the codebase allowed to import `langgraph`
(ADR-0024, enforced by `tests/test_architecture.py` and a ruff banned-api rule, the same
mechanism ADR-0002 uses for `langchain*`). Topic matching (above) runs entirely outside
this graph, in plain Python -- nothing to fan out, it's a single batched call.

```
START
  |  Send fan-out, one branch per topic_id (independent -- a topic already
  |  curriculum'd and just topping up cards never waits on a sibling topic
  |  still doing its first curriculum pass)
  v
resolve_and_plan_topic
  - the topic already exists (matching decided that upstream)
  - if curriculum_generated_at is unset: one generate_curriculum() call,
    persist Subtopic rows (grouped across difficulty tiers via
    subtopic_group_id -- the model decides which tiers a concept needs,
    never a mechanical beginner+intermediate+advanced grid)
  - if already curriculum'd: skip straight to loading existing subtopics
  |
  | Send fan-out, one branch per subtopic GROUP (not per tier -- see below)
  v
generate_subtopic_cards
  - concurrent across groups AND topics
  - tiers WITHIN one group run sequentially, lowest difficulty first: a
    linked higher tier's generate_cards() call receives the lower tier's
    actual card BODIES as `builds_on` context, so it can genuinely build on
    them rather than just avoid repeating titles. Groups with one tier (the
    common case) are unaffected -- nothing to sequence.
  - gates+persists its OWN group's cards and questions itself, right here,
    before returning (ADR-0041) -- runs the two-pass quality gate (ADR-0030):
    a structural check (generation/gate.py), pass 1 correction and pass 2
    verification (both thinking-pool LLM calls, concurrent across this
    group's subtopic-tiers), and near-duplicate detection (local embeddings,
    sequential, between the two passes) -- every draft becomes exactly one of
    an active `Card` or a `rejected_card` row. Accepted cards get embedded,
    archetype-derived, and bootstrap `CardStats`. THEN generates questions
    FROM the cards just persisted, per subtopic/difficulty, and persists
    those too (Question rows) -- all before this branch returns, so a card
    goes live in the feed as soon as ITS OWN group is done, not held back for
    every other group/topic in the run.
  - the first draft-and-gate round above is NOT the end of a tier's work: the
    gate rejects some fraction of every batch, so drafting a tier to its full
    `target_cards` exactly once and gating once routinely lands under target
    even on a run that returns without error. `_redraft_until_bar` (ADR-0057)
    runs after every group's first round completes, redrafting and re-gating
    per subtopic-tier, round after round, until each tier clears a completion
    bar (90% of target on a tier's first-ever pass, 100% on any later pass --
    e.g. a `scan_and_generate` backfill) or a per-tier stuck guard concludes
    the gate is genuinely, repeatedly rejecting its content (logged as
    REJECTED) or the generator calls themselves are failing (logged as
    FAILED, tracked separately -- see ADR-0057).
  |
  | fan-in (every branch's item_reports merge, across every topic in the run)
  v
gate_and_persist
  - everything is ALREADY persisted by this point. Final, lightweight step:
    aggregates every group's item_reports into the run's per-topic report,
    and marks each topic's GenerationJob done. Fan-in is correct HERE (unlike
    for the actual writes) since the final report and "done" flag genuinely
    do need every group finished.
```

Every real generator call (curriculum, topic matching, card generation, question
generation) goes through a shared `asyncio.Semaphore` (`SPOIN_MAX_CONCURRENT_GENERATION_CALLS`)
-- without it, a run with several topics times many subtopics each would fire dozens of
simultaneous calls, well past any ladder rung's per-minute limit (ADR-0028).

## Worker: per-job isolation, not graph-level fan-out

`apps/worker`'s `run_once()` claims pending `GenerationJob` rows, marks them `running` in
that same transaction, then fires one `asyncio` task per job -- **each with its own DB
session** -- gathered together. One job's exception marks only that job `failed`; it never
touches any other job in the same pass (ADR-0026). This is a different concurrency layer
from the graph's own `Send` fan-out above: the graph still owns concurrency *within* one
topic's run (subtopics, tiers); the worker owns concurrency *across* jobs.

`run_generation_pipeline` still accepts a list of topic_ids (the CLI can hand it several
at once, sharing one session -- fine for a manual run where isolation doesn't matter); the
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
`existing_titles`) -- deliberately. An earlier version of this added a second
embedding-column + LLM-judge layer purely for subtopic reconciliation, mirroring
ADR-0025's topic-matching machinery one level down. It was removed: subtopics are
reconciled once per topic (not repeatedly, at volume, the way cards are), so the
detection-layer complexity ADR-0007 accepts for cards wasn't earning its cost here. The
curriculum call already has full context to make this a single "taste" decision in the
same request, the same trust level as everything else in that call.

## Two generator backends

`SPOIN_GENERATOR` selects which `ContentGenerator` implementation
`generation.get_content_generator()` returns:

- **`fake`** (default, everywhere except a deliberate switch) -- `generation/fake.py`.
  Deterministic, in-memory, no network, no quota. This is what every automated test and
  the CLI examples above run against.
- **`gemini`** -- `generation/langchain_impl.py`. The only module allowed to import
  `langchain*` (ADR-0002/0024). Requires `SPOIN_GEMINI_API_KEYS` (comma-separated); raises
  a clear config error at construction if unset, rather than failing mid-run.
  **Connectivity live-verified 2026-08-17, prompt quality still not.** Covered by mocked
  unit tests (`tests/test_langchain_impl.py`: structured-output parsing, per-item
  validation, partial-failure handling, the batched matching call), and the model
  **rotation mechanism** ([ADR-0028](../adr/0028-key-model-quota-ladder.md)/[0029](../adr/0029-questions-join-generator-pool.md))
  now has its ladder model ids confirmed live against 9 real keys -- see ADR-0008's
  updated "Open question" section. What's still unverified: whether the prompts in this
  file produce *good* output. Treat the prompts as a first draft even though the models
  behind them are now confirmed reachable.
- **`local`** -- not implemented (ADR-0008).

Switching backends is a `.env` change only; nothing else in the pipeline knows or cares
which one is behind the interface.

### Quota governance

**Redesigned in [ADR-0028](../adr/0028-key-model-quota-ladder.md), pool assignment amended
in [ADR-0029](../adr/0029-questions-join-generator-pool.md)** -- read those for the full
reasoning; this is the short version. `generation/quota.py`'s `QuotaGovernor` tracks a grid
of `(key_index, model)` cells, not a flat list of keys: Gemini rate limits are per *project*
(so each `SPOIN_GEMINI_API_KEYS` entry only helps if it's a genuinely separate project) and
per *model* independently (so exhausting one model's daily quota doesn't touch another's).
`GeminiContentGenerator` holds TWO governors -- a "thinking" pool (curriculum, topic
matching, judging, quiz grading -- `SPOIN_GEMINI_THINKING_LADDER`) and a "generator" pool
(`generate_cards` AND `generate_questions`, both high-volume per-item prose --
`SPOIN_GEMINI_GENERATOR_LADDER`), each an ordered model-fallback ladder. RPD is persisted in
`QuotaLedger` (`backend=f"gemini:{key_index}:{model}"`); RPM is in-process only and resets
each worker
run. `QuotaExhaustedError` is caught specifically at the worker's job boundary and requeues
the job as `pending` rather than `failed` (safe because the pipeline is idempotent per
topic, ADR-0026). Wired end to end and unit-tested (`tests/test_quota_governor.py`,
`tests/test_worker.py`'s requeue test). Each key's connectivity and each ladder model id
is now live-confirmed (see above), and the grid's rotation under real exhaustion has now
been triggered end to end for real (not just simulated) -- which is also how
[ADR-0040](../adr/0040-per-cell-call-serialization.md) got found: `acquire()` granting a
cell and returning before the actual call fires let concurrent tasks burst a single cell
past its real RPM, producing 429s the local ledger didn't expect. Fixed by serializing
same-cell calls; see that ADR for the full story.

**A stalled call now has a client-side timeout and its own recovery path**
([ADR-0056](../adr/0056-generation-call-timeout-and-recovery-probe.md)), found the same way
as ADR-0040: a real hang (`POST /topics` never resolving) traced back to
`ChatGoogleGenerativeAI` having no `timeout`, so a stalled call never raised anything for
`_invoke_with_retry` to catch. Fixed with a configured timeout
(`gemini_request_timeout_seconds`) plus a persistent, cross-call model exclusion and a
background probe that cycles through a different key each attempt to check when the model's
come back -- read that ADR for why the exclusion needed to outlive a single call, and for the
caveat that the probe mostly only completes in a long-lived process (the API process, not
the worker's short cron pass).

## What's missing

- **Only one thing creates `GenerationJob` rows so far.** `POST /topics`
  (`api/routers/topics.py`) enqueues one when a user-typed topic name genuinely misses
  ADR-0025's matcher -- that's the only trigger that exists. Nothing yet refills an
  existing topic that's running thin (ADR-0026 §"open question"), and there's no
  admin-triggered path either.
- **The quality gate is built** (ADR-0030, content-model.md's "Quality gate" section):
  structural check, pass 1 correction, near-duplicate detection, pass 2 verification, all
  wired into `generate_subtopic_cards`'s per-group gate call (`_gate_and_persist_results`,
  [ADR-0041](../adr/0041-per-group-gate-and-persist.md) -- persistence moved off the old
  global `gate_and_persist` fan-in, which now only aggregates the final report and marks
  topics done). `card_duplicate_threshold` (0.9) remains an explicit, uncalibrated
  placeholder -- see content-model.md's open questions -- and the hand-curated
  `difficulty_examples` catalog is unauthored (docs/tasks/0011), so standalone
  subtopic-tiers currently get no calibration examples in practice.
- **Live Gemini verification, and the model-choice question itself.** See above.
