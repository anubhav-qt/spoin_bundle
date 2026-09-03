# ADR-0084 load balancer: send-gap benchmarks (2026-09-03)

> **UPDATE (2026-09-04):** Root cause confirmed and resolved in [ADR-0085 benchmarks](adr-0085-concurrency-burst-benchmarks.md) and [ADR-0086](../adr/0086-concurrency-staggering-and-initial-dispatch-jitter.md). The bare 429s were Google edge gateway load shedding on simultaneous in-flight heavy payloads. Resolved by prompt token packing (ADR-0085) and pool-wide dispatch staggering / initial jitter (ADR-0086).

Three benchmarks tried to find a per-cell send rate Gemini accepts. **None found
one, and the evidence says the send rate is not the variable that matters.**

## Results

| Bench | Box | Gap | Rate/cell | 429 rate | Cards |
|---|---|---|---|---|---|
| 1 | 34 keys x 2 topics | 4s | 15/min | ~95% (`AllCellsThrottledError` in 10 min) | +0 |
| 2 | 75 keys x 1 topic | 4s | 15/min | ~85% (spin-wait, no terminal error) | +0 |
| 3 | 75 keys x 1 topic | 10s | 6/min | **83.9%** (540 429 / 104 200) | **+0** |

Bench 3: topic "Generative AI", 16:54:31-17:00 UTC, killed after ~6 min.
Cards stayed at 138. 1775 `no generator cell right now` starvation waits.

**Cutting the send rate 2.5x moved the 429 rate by one point (85% -> 84%).**
If our pacing were the binding constraint, 429s would have fallen roughly with
the rate. They did not. Per-cell pacing is not the variable.

## What the keys actually do (measured, not inferred)

Re-ran the 2026-09-01 solo-ceiling probe (`key_cluster_probe.py A`, burst 25
concurrent, `gemini-3.5-flash-lite`) on 10 keys spread across the pool, minutes
after bench 3 died:

```
key   0,5,12,20,30,40,60,68  ok=16/25   quota=GenerateRequestsPerMinutePerProjectPerModel-FreeTier
key  50                      ok=15/25   (1 transport error)
key  74                      ok= 3/25   quota=GenerateRequestsPerDayPerProjectPerModel-FreeTier
```

- The keys are **healthy and distinct**, reading exactly the 16 req/min ceiling
  measured on 2026-09-01. Owner's claim that all keys are separate projects is
  independently confirmed. Key 74 is genuinely per-day spent (matches its `500`
  `quota_ledger` row).
- **Ruled out:** shared projects, account-level flagging/anti-abuse throttling,
  per-day exhaustion, and a leaked global credential (`GOOGLE_API_KEY`,
  `GOOGLE_APPLICATION_CREDENTIALS` et al. are all unset in the `api` container,
  so each client really does use its own key).

So the key->project audit (handoff `next-key-projects-and-experiment-restore.md`
Job 1) is **closed**: there is nothing left to prune.

## The contradiction that remains

Direct httpx calls and the pipeline hit the same keys, model and endpoint
minutes apart, and get **different 429s**:

- Probe: a proper quota 429 carrying
  `quotaId=GenerateRequestsPerMinutePerProjectPerModel-FreeTier` + `RetryInfo`.
- Pipeline: **539 of 540** are a bare envelope with no `details` array at all --
  `{'code': 429, 'message': 'Resource has been exhausted (e.g. check quota).',
  'status': 'RESOURCE_EXHAUSTED'}` -- which `langchain_impl.py`'s parser
  (`raw = getattr(exc, "details", None)`) logs as "no recognizable scope".

And the pipeline earns these at a per-cell rate that cannot violate a 16/min
limit: `_FLUSH_EVERY = 10` and **zero** `quota_ledger` flushes across bench 3's
~660 requests, so no single cell reached even 10 requests in 6 minutes. Wide
spread, ~1-2 req/min per cell, against keys measured at 16/min -- yet 84% 429.

**A healthy 16/min key returning per-minute 429s at 1-2/min is the thing to
explain.** See "The likely cause" below -- found while fixing the two bugs.

## ROOT CAUSE (2026-09-03, bench 4 + isolation tests): large prompts under concurrency

**Reproduced outside the pipeline entirely.** N distinct keys, one
`ChatGoogleGenerativeAI` each, all firing at once, `gemini-3.5-flash-lite`:

| prompt | structured output | concurrency | bare 429s |
|---|---|---|---|
| ~16k tokens | no | 40 | 27/40 |
| ~16k tokens | yes | 40 | 19/40 |
| ~10 tokens | yes | 40 | **0** |
| ~10 tokens | no | 40 | **0** |
| ~16k tokens | yes | sequential, 7.5/min | **0** |

**Prompt SIZE under CONCURRENCY is the trigger.** Structured output is innocent
(small+struct is clean, big+no-struct fails). The limit is not per-project: each
key carried only ~16k tokens against a 250k per-project TPM. It is an aggregate
token throttle across the whole client, and it reports as the bare
`RESOURCE_EXHAUSTED` with no `quotaId` -- which is why it never looked like a
documented quota.

It also DEPLETES under sustained load and does not refill in ~25s. Two identical
sweeps back to back:

```
round 1:  10x16k -> 0 bare    20x8k -> 5 bare    40x4k -> 28 bare
round 2:  10x16k -> 10 bare   20x8k -> 20 bare   40x4k -> 36 bare
```

Everything else is RULED OUT by direct measurement:

- **Keys** are healthy and distinct -- 16/25 solo ceiling, twice, including
  *while the pipeline was 429ing on those same keys*.
- **Aggregate request rate** is not it: raw httpx at 240 req/min across 75 keys
  gave 11% 429, every one an attributed per-DAY 429 from the ~11 keys already
  at their 500 cap. Zero per-minute 429s, zero bare envelopes.
- **The SDK** is not it: 40 concurrent tiny calls through
  `ChatGoogleGenerativeAI` gave 36 ok / 4 attributed 429.
- **Per-IP request limiting** is not it (same 240/min test).
- **Our pacing** is not it -- see the next section; it works.

### Why every benchmark failed the same way

Adding keys cannot help, because the ceiling is not per-key. Slowing the
per-cell send gap cannot help, because the binding constraint is how many large
prompts are in flight at once -- roughly 45 subtopic-group branches fan out
together. That is why bench 1 (34 keys), bench 2 (75 keys), bench 3 (10s gap)
and bench 4 all landed in the same 84-95% band.

### Still unknown

- The exact ceiling and refill rate (the two rounds above differ too much to
  fit a curve; sustained load matters and I did not idle long enough to measure
  recovery).
- **The real pipeline's prompt size.** All of the above used a synthetic ~16k
  token prompt. The actual card/question prompts have not been measured, and
  any fix needs that number to be sized.

## Superseded theory: the gap is enforced at RESERVATION time, not SEND time

**This was wrong -- probe A disproved it.** Kept for the reasoning trail.

`_invoke_with_retry` (`langchain_impl.py:1103-1111`) does:

```python
res = await lb.assign(kind, now=...)        # gap checked HERE, stamps last_send
...
async with lb.cell_lock(key_index, model):  # then QUEUES on the cell lock
    result = await self._invoke_with_backoff(...)   # ... and only now sends
```

`assign()` spaces *reservations* by the gap. It has no idea a call is already
in flight on that cell, because `cell_lock` is acquired afterwards. So with call
latency `L` and gap `G`, up to `L/G` coroutines legally reserve the same cell
while one holds the lock -- and when the lock frees they fire back to back, as
fast as the API answers. The gap believed they were `G` apart; the provider saw
a burst.

This predicts everything observed:

- **Wide spread, low average, still 429.** Each cell stays under `_FLUSH_EVERY`
  over the pass (no ledger flush, as seen) while still emitting short bursts.
  A per-minute limit is violated by the burst, not the average.
- **Why a 2.5x slower gap barely helped.** Queue depth is `L/G`. Structured-output
  calls on big prompts run tens of seconds, so at `L≈30s` the depth only fell
  from ~7 (G=4s) to ~3 (G=10s) -- still a burst. 85% -> 84%. If pacing were the
  real limiter, 429s would have fallen with the rate.
- **Why the keys probe clean.** They are clean. The burst is ours.

`note_send` re-anchors `last_send` to the true send time, which fixes the
*next* reservation -- but the coroutines already queued behind the lock never
re-check the gap.

**Disproved by probe A** (bench 4, 332 sends over 140 cells): true spacing
between consecutive sends to the same cell was p50 **49.5s**, p10 10.2s, and
only 4.7% of pairs were closer than the 10s gap -- one per cell, no repeat
bursting. `queued` (reserve->send) was p50 0.00s, p90 0.01s, so nothing was
piling up behind `cell_lock` at all. Predicted queue depth L/G came out 0.7.
The pacing works; the cells were being hit ~1.2 times a minute and still 429ing.

The original proposal, now moot: enforce the gap where the send actually happens. After acquiring
`cell_lock`, sleep whatever remains of `_gap_for(cell)` since `last_send`
before invoking. The lock already serialises the cell, so the wait is correct
and cheap. Alternative: have `assign()` refuse a cell with a call in flight,
which converts the burst into balancer-visible pressure instead of hiding it.
 Not yet settled. The next experiment should be: drive the pipeline's
own client (`ChatGoogleGenerativeAI`, `max_retries=0`) against one idle key at a
known slow rate and dump the raw exception. If it reproduces the bare envelope,
the difference is a client-library artifact and the 429 is real (something is
bursting that the per-cell gap does not see). If it does not, the fault is in
how the pipeline builds or routes the request.

## Two bugs fixed (2026-09-03, uncommitted)

1. **The send gap is global, but the ladders have different `rpm`.**
   `gemini_send_gap_seconds` is one constant applied to every cell
   (`load_balancer.py:355-362`), while `gemini_thinking_ladder` is `rpm=5`
   (needs a 12s gap) and `gemini_generator_ladder` is `rpm=15` (needs 4s). At a
   4s gap every thinking cell was driven 3x over its limit; at 10s, 1.2x over.
   **Fixed:** `LoadBalancer._gap_for(cell)` returns
   `max(configured_gap, 60 / rung.rpm)` -- the setting is now a floor that can
   slow the pool down but can never drive a rung past its own ceiling.
   Regression test: `test_send_gap_never_outruns_a_slow_rungs_own_rpm`.
   (Not the cause of these benchmarks -- bench 3's 429s were almost entirely
   flash-lite, with a single thinking call -- but it is wrong.)

2. **An unattributed 429 costs a full 60s cooldown.** No `RetryInfo` means
   `_COOLDOWN_S = 60.0` (`load_balancer.py:445`). At an 84% 429 rate, cells park
   faster than they return, which is what produced the 1775 starvation waits and
   bench 2's terminal-error-free spin-wait. **Fixed:** the cooldown is now
   `min(now + 60, oldest_live_send + 60)` -- the cell's own window measured
   rather than a flat minute assumed; `_COOLDOWN_S` stays the bound for a cell
   with an empty window. Regression test:
   `test_unattributed_429_cooldown_credits_the_window_already_served`.
   This amplifies the failure; it does not start it.

3. **`assign()` advanced a synthetic clock by the nominal sleep.**
   `now = now + timedelta(seconds=wait_s)` after `await asyncio.sleep(wait_s)`,
   which on a loaded loop returns much later than `wait_s`. Across bench 3's
   1775 waits that clock drifts far behind real time, and the stamp a
   reservation writes to `last_send` then understates how recently the cell was
   used -- un-blocking the gap early. **Fixed:** advance by
   `max(wait_s, monotonic elapsed)`. A third change beyond the two asked for;
   small and same-file, revert if unwanted.

## Follow-up needing owner approval (a write to `spoin_db_2`)

Today's `quota_ledger` has 11 cells pinned at the 500/day cap from a
pre-ADR-0084 orphaned run, against 430 rows totalling 7747 requests. They seed
the balancer as spent when they are not. Small effect (11 of ~150 generator
cells), but it makes the seeds dishonest. Not actioned.
