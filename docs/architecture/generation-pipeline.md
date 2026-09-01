# Generation pipeline -- how the corpus gets filled

> Prerequisite: [`overview.md`](overview.md) and [`content-model.md`](content-model.md).
> This document is the implementation-level companion to
> [ADR-0025](../adr/0025-batched-llm-topic-matching.md) (topic matching),
> [ADR-0026](../adr/0026-one-shot-generation-to-completion.md) (the one-shot execution
> model), [ADR-0007](../adr/0007-curriculum-driven-generation.md) (curriculum-driven
> generation), and [ADR-0024](../adr/0024-langgraph-for-card-generation-pipeline.md) (why
> LangGraph, and what it does and doesn't own). Read those for *why*; this doc is *what
> exists and how to run it*.
>
> Diagrams (theme-aware HTML, open in a browser):
> [`diagrams/generation-pipeline.html`](diagrams/generation-pipeline.html) -- every step,
> model tier, rejection path and feedback loop of the pipeline **as it stands today**;
> [`diagrams/generation-pipeline-redesign.html`](diagrams/generation-pipeline-redesign.html)
> -- a **proposed** re-pooling that pulls THINKER calls out in favour of GENERATOR feedback
> loops (target design, not built).

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
                              subtopic per difficulty tier -> then, once every
                              subtopic's cards are done, questions for the whole
                              topic (ADR-0074). Idempotent per topic -- calling it
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
  - per subtopic-tier, ONE plan_cards() call first (ADR-0059, generator pool):
    the pre-processing gate. It is the only call that sees a whole tier at
    once, so it is the only one that can make the tier's cards differ
    deliberately rather than by accident -- it returns one brief per card
    (concept, form, what the diagram/code/art shows, and the angle that
    separates it from its siblings), and the writer calls below are handed
    their slice instead of re-inventing coverage from a list of titles that
    happened to land first. A failed or empty plan falls back to unplanned
    generation, which is exactly the pre-ADR-0059 path -- planning improves
    what gets written, it is never a prerequisite for writing anything.
    The plan's card_type is a REQUEST: the realised type mix is still counted
    against the tier's quota in code afterwards, unchanged (trusted for taste,
    never for constraints).
  - then ONE fetch_ascii_scenes() call (ADR-0080, generator pool) over the
    tier's `ascii` briefs: for each, retrieve the top-10 curated gag scenes by
    `asset_direction` similarity -- EXCLUDING every scene already used anywhere
    in this topic (`topic_used_ascii_ids`: active cards' `visual_slots.src_id`
    plus rejected drafts' `gen_meta.src_id`, so a scene is single-use per topic
    for its whole life) -- and the model picks one and captions it from the
    directions. A matched brief carries its scene on `CardPlan.fetched_scene`;
    the writer is told "art: PROVIDED" and does not draw it, and the pipeline
    stamps the scene (with its `src_id`) onto the draft. A brief the fetcher
    can't match ("art: draw one") falls through to the writer's free-draw path
    (ASCII_INSTRUCTIONS), the rare case. An empty/failed fetch = every ascii
    card free-draws, exactly the pre-ADR-0080 path.
  - tiers WITHIN one group run sequentially, lowest difficulty first: a
    linked higher tier's generate_cards() call receives the lower tier's
    actual card BODIES as `builds_on` context, so it can genuinely build on
    them rather than just avoid repeating titles. Groups with one tier (the
    common case) are unaffected -- nothing to sequence.
  - claims ONE key for this whole branch (ADR-0074) and holds it until the
    branch returns -- planning, every draft round, both gate passes, every
    redraft. At most one group per key is in flight, which is the entire
    concurrency bound.
  - gates+persists its OWN group's cards itself, right here, before returning
    (ADR-0041) -- runs the two-pass quality gate (ADR-0030):
    a structural check (generation/gate.py), pass 1 correction and pass 2
    verification (both thinking-pool LLM calls, concurrent across this
    group's subtopic-tiers), and near-duplicate detection (local embeddings,
    sequential, between the two passes) -- every draft becomes exactly one of
    an active `Card` or a `rejected_card` row. Accepted cards get embedded,
    archetype-derived, and bootstrap `CardStats`. A card goes live in the feed
    as soon as ITS OWN group is done, not held back for every other
    group/topic in the run. Questions are NOT written here since ADR-0074 --
    see `gate_and_persist` below.
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
    FAILED, tracked separately -- see ADR-0057). Redraft rounds plan too
    (ADR-0059) -- a tier that landed short is the one whose remaining cards
    are hardest to place, and the redraft's plan_cards() call is the only one
    that sees the tier's fresh rejection context before choosing what to
    attempt next.
  - everything persisted here -- cards and rejected drafts, and questions in
    the phase below --
    carries `gen_meta.prompt_version` (ADR-0059), recording which generation
    of the prompts produced it. This is NOT `Card.version`, which is
    family-scoped regeneration lineage and unrelated. Content written before
    ADR-0059 has no such key and is v1 by absence; query it as
    `gen_meta->>'prompt_version' IS NULL`.
  |
  | fan-in (every branch's item_reports merge, across every topic in the run)
  v
gate_and_persist
  - every CARD is already persisted by this point. This node owns the topic's
    QUESTION phase (ADR-0074): now that every group has cleared its card bar,
    one concurrent unit per subtopic-tier -- each claiming a key exactly like a
    card branch does -- writes that tier's questions from its FINISHED card
    set. Questions used to run per group, alongside that group's cards; they
    run here so a tier's question budget is spent against what the subtopic
    actually ended up containing, rather than against whichever cards survived
    its first gate round only for a redraft round to add more afterwards.
  - then aggregates every group's item_reports into the run's per-topic report
    and marks each topic's GenerationJob done. Fan-in is correct HERE (unlike
    for the card writes) since the questions, the final report and the "done"
    flag genuinely do need every group finished.
```

**Concurrency is bounded by the KEY POOL, not by a semaphore**
([ADR-0074](../adr/0074-key-per-subtopic-scheduling.md),
[ADR-0078](../adr/0078-topic-parallel-key-leases.md)). There used to be a shared
`asyncio.Semaphore` here; [ADR-0047](../adr/0047-removal-of-legacy-concurrency-semaphore.md)
deleted it after measuring a 33-key pool being throttled to five calls at a time, and
ADR-0074 replaced the *idea* of a global cap with key ownership: a subtopic group claims
one key when its branch starts and holds it for the whole of its card work -- `plan_cards`,
every draft round, both gate passes, every redraft -- releasing it when the group clears
its bar. One caller per key is what makes an rpm violation structurally impossible rather
than merely counted; `tests/test_architecture.py` fails if a semaphore ever comes back.

**Since [ADR-0078](../adr/0078-topic-parallel-key-leases.md) many topics run at once**, so
the pool is divided into per-topic **leases**: a topic takes `N` keys for its whole run,
`N` = the most subtopics in any one of its difficulty tiers (the widest it can fan out).
A subtopic group then claims its one key *from its topic's lease*; group K+1 waits when the
lease's keys are all held by siblings. When a group's key is spent on the strong models it
**borrows a key from the shared reserve** (keys in no lease) for that one call rather than
dropping a rung on the key it holds -- see ADR-0078's ladder. The worker packs the pending
queue so `sum(N) <= pool_size` before a pass runs, and leaves the overflow `pending`.

## Worker: per-job isolation, not graph-level fan-out

`apps/worker`'s `run_once()` claims pending `GenerationJob` rows, **admits as many as the
key pool can hold at once** ([ADR-0078](../adr/0078-topic-parallel-key-leases.md) --
`sum(N) <= pool_size`, `N` = a topic's widest tier; a topic with no curriculum yet gets a
provisional `default_topic_key_budget`), marks only the admitted rows `running` in that
same transaction, then fires one `asyncio` task per admitted job -- **each with its own DB
session** -- gathered together. Unadmitted rows stay `pending` for the next pass. One job's
exception marks only that job `failed`; it never touches any other job in the same pass
(ADR-0026). This is a different concurrency layer from the graph's own `Send` fan-out
above: the graph owns concurrency *within* one topic's run (subtopics, tiers) against that
topic's key lease; the worker owns concurrency *across* jobs.

`run_generation_pipeline` accepts a list of topic_ids plus a `key_budgets` map (the CLI
hands it several at once sharing one session, and no budgets -- each topic then leases at
`default_topic_key_budget`); the worker calls it with a single-item list per job, passing
that job's admitted budget.

ADR-0073 briefly made this loop strictly sequential (one topic finished before the next
started); ADR-0078 restored the concurrent `gather` with the admission step in front.

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
reasoning; this is the short version. **Since [ADR-0074](../adr/0074-key-per-subtopic-scheduling.md) the governor is also
the key ALLOCATOR**: a subtopic group claims a key (`claimed_key_scope()`, one
`KeyClaimRegistry` shared by both pools) and `acquire()` then walks that key's own rungs
first -- 3.7, then 3.6, then, only once no unclaimed key has room, 3.5. The weakest rung
(`gemini_thinking_reserve_rungs`) is held back as a reserve: it is reached when no key
anywhere has daily room on an ordinary rung, never merely because every key is busy --
contention waits, exhaustion descends. `generation/quota.py`'s `QuotaGovernor` tracks a
grid of `(key_index, model)` cells, not a flat list of keys: Gemini rate limits are per *project*
(so each `SPOIN_GEMINI_API_KEYS` entry only helps if it's a genuinely separate project) and
per *model* independently (so exhausting one model's daily quota doesn't touch another's).
`GeminiContentGenerator` holds TWO governors -- a "thinking" pool (curriculum, topic
matching, judging, quiz grading -- `SPOIN_GEMINI_THINKING_LADDER`) and a "generator" pool
(`plan_cards`, `fetch_ascii_scenes`, `generate_cards` AND `generate_questions` -- high-volume,
and upstream of the gate rather than a substitute for it, ADR-0029/0059/0080 --
`SPOIN_GEMINI_GENERATOR_LADDER`), each
an ordered model-fallback ladder. RPD is persisted in
`QuotaLedger` (`backend=f"gemini:{key_index}:{model}"`); RPM is persisted too since
ADR-0058 (`QuotaRequest`, a trailing-60s window). Within a rung, keys are tried
**least-spent first** ([ADR-0065](../adr/0065-quota-governor-fairness-accounting-and-terminal-states.md)),
not index order -- first-fit from key 0 was measured making a 33-key pool behave like a
9-key one. That ADR also: refunds a cell's daily charge when the call comes back a
per-minute 429 (the provider didn't count it, so neither do we); gives each cell a
**learned effective rpm** that halves on a 429 and grows back on success, so the governor
converges on the real per-project ceiling instead of trusting the configured number; and
splits `QuotaExhaustedError` into `DailyQuotaExhaustedError` / `AllCellsThrottledError` /
`AllModelsUnavailableError` so a provider outage can't be reported as a spent daily budget.
The base `QuotaExhaustedError` is still caught at the worker's job boundary and requeues
the job as `pending` rather than `failed` (safe because the pipeline is idempotent per
topic, ADR-0026); the subclass is recorded in `GenerationJob.last_error` so a stalled queue
says *why*. Wired end to end and unit-tested (`tests/test_quota_governor.py`,
`tests/test_worker.py`'s requeue test). Each key's connectivity and each ladder model id
is now live-confirmed (see above), and the grid's rotation under real exhaustion has now
been triggered end to end for real (not just simulated) -- which is also how
[ADR-0040](../adr/0040-per-cell-call-serialization.md) got found: `acquire()` granting a
cell and returning before the actual call fires let concurrent tasks burst a single cell
past its real RPM, producing 429s the local ledger didn't expect. Fixed by serializing
same-cell calls; see that ADR for the full story.

**Not every 429 is an exhaustion** ([ADR-0058](../adr/0058-per-minute-vs-per-day-429.md)).
The provider's error envelope carries a `quotaId` saying which limit was hit, and the two
demand opposite responses: a `...PerMinute...` 429 parks the cell for the `retryDelay` it
also ships (`mark_rate_limited`, ledger untouched, `acquire()` sleeps it out), while only a
`...PerDay...` 429 spends the cell for the day (`mark_exhausted`). Treating them alike is
what produced a run that stopped with "All 17 key(s) x 2 model(s) exhausted" on keys holding
nearly their full daily quota. **When a run reports exhaustion, check which subclass**
(ADR-0065) -- and, on the base message, check the logs for `hit a per-minute rate limit`
before believing the daily count. Note that `quota_ledger.requests_spent` is only a
truthful measure of the day's consumption *since* ADR-0058; before it, a 429 could reset
the count to zero, and since ADR-0065 a per-minute 429 *decrements* it (the refund above).

**A stalled call now has a client-side timeout and its own recovery path**
([ADR-0056](../adr/0056-generation-call-timeout-and-recovery-probe.md)), found the same way
as ADR-0040: a real hang (`POST /topics` never resolving) traced back to
`ChatGoogleGenerativeAI` having no `timeout`, so a stalled call never raised anything for
`_invoke_with_retry` to catch. Fixed with a configured timeout
(`gemini_request_timeout_seconds`) plus a cross-call model exclusion and a background probe
that cycles through a different key each attempt to check when the model's come back -- read
that ADR for why the exclusion needed to outlive a single call, and for the caveat that the
probe mostly only completes in a long-lived process (the API process, not the worker's short
cron pass). Since ADR-0065 that exclusion is a `model_unavailable` DB row with an expiry
(the probe's own budget), not per-process memory -- so a 504 outage one process finds isn't
rediscovered, one timeout at a time, by every other process and both pools.

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
