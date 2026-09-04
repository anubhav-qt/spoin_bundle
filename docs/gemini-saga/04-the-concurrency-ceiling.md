# 4. The concurrency ceiling

> **2026-09-04.** The day the actual constraint was measured directly instead of
> inferred from pipeline runs. Source-of-truth handoff:
> [ip-concurrency-ceiling-and-inflight-semaphore.md](../handoff/ip-concurrency-ceiling-and-inflight-semaphore.md).

## The finding

**Google's free-tier edge gateway sheds on CONCURRENCY — how many requests from
this source IP are simultaneously awaiting a response — not on send rate, not on
key count, not on token volume.**

`inflight_sweep.py` held *exactly N* requests open at once (each worker: call →
await the full response → next call), sustained for 150s per arm, ~8k-token
prompts:

| N in flight | failure | bare 429s | good calls/s |
|---|---|---|---|
| 2 | 1.5% | 0 | 0.85 |
| 3 | 1.2% | 0 | 1.11 |
| **4** | **53.6%** | **220** | 1.31 |
| 5 | 48.4% | 200 | 1.49 |

**A hard wall between 3 and 4. Not a gradient.** Zero perimeter shedding at N≤3.

Two corroborating measurements:

- The first pipeline run that day used a *pure send-rate limiter* — one request
  dispatched every 2s, i.e. 0.5 sends/s, **lower** than the clean single-stream
  probe's rate — with no cap on in-flight. Result: **73% failure**, because ~4–10
  structured calls (each 7–17s) were open at once. Rate was fine; concurrency was
  not.
- Direct single-key probes: **12 keys from 12 separate Google projects, fired
  concurrently, all returned an IDENTICAL `retryDelay` (32s)** — and firing them
  is what re-armed a window that had just decayed to 0s. The envelope's
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 500` label is
  boilerplate; those keys were nowhere near 500 requests.

**The throttle is keyed to the source IP.** Every key in the pool shares one
budget of three concurrent requests. This retroactively explains the entire
collapse in [document 2](02-the-collapse.md): growing the pool 33 → 75 → 109 keys
bought nothing, because keys were never the scarce resource.

## The second finding: a transient IP penalty

Google's free-tier daily reset is at **~07:00 UTC** (midnight Pacific), not 00:00
UTC. `keycount_probe.py` at a fixed 30 req/min, varying only how many distinct keys
the traffic spread across:

- **Before the reset**, after ~10h of aggressive benchmarking: 20 keys → 18.9%
  failure, 30 → 32.2%, 108 → 42.2% and climbing. A real gradient with key count.
- **After the reset**, same harness: 20/30/50 keys → **5.6% / 3.3% / 3.3%**, flat,
  no gradient. Re-measured twice.

So **sustained hammering accrues a soft penalty on the IP that the daily reset
clears**, and key count only mattered *while penalised*. This also means any
measurement taken after a heavy failing run is measuring a penalised IP — a
methodological trap that cost real time.

A consequence worth keeping: `quota.py`'s `_day_start()` now rolls at 07:00 UTC.
A run launched between 00:00 and 07:00 UTC was seeding every cell from a
freshly-rolled empty ledger while Google still counted the previous evening's
spend, producing genuine per-day 429s on apparently fresh keys.

## The classification bug that liquidated the pool

Benchmark 10's collapse had a second cause, independent of concurrency. A 429
carrying a `...PerDay...` `quotaId` was classified as a daily exhaustion, which
force-sets `rpd_spent = rpd_limit` **and** flushes a fabricated `500` into
`quota_ledger` that the *next run* seeds from. Google was attaching that
boilerplate `quotaId` to short-`retryDelay` throttles. Result: **136 of 204
generator cells destroyed in 60 seconds**, and the damage persisted across runs.

Fix: a short `RetryInfo` (≤60s) now **outranks** a `PerDay` `quotaId` — no per-day
exhaustion resolves itself inside a minute. This is
[ADR-0058](../adr/0058-per-minute-vs-per-day-429.md)'s core idea holding up, with
the evidence ordering corrected.

## Mechanism 1: the rolling semaphore

An `asyncio.Semaphore(3)` at the single outbound send site in `langchain_impl.py`.
Every generation call — card drafts and thinking calls, box balancer and remainder
balancer alike — acquires a permit before its request leaves and releases it when
the response lands.

Live result: **clean, 0 x 429, for ~5 minutes** (09:16–09:20). Then, exactly when
curriculum/planning finished and full drafting fan-out began:

```
09:16-09:20   0 x 429/min
09:21        65 x 429/min
09:22       104 x 429/min
09:24       107 x 429/min
```

83 cards persisted, 338 cards/hr, 0 force-killed cells, 0 terminal errors — the
safety net held, it just got slow. `inflight_sweep.py` at N=3 had stayed clean for
its full run; the pipeline at nominal-3 did not. Three hypotheses were left open:

- **(a)** Sustained *large-batch* load re-triggers the transient penalty faster
  than N=3 small calls do.
- **(b)** The fan-out phase transition briefly pushed real concurrency past 3.
- **(c)** The edge sheds on connection-*seconds* or bytes in flight, so 3 x 17s
  calls is not the same as 3 x 2.5s calls, and the true ceiling for pipeline-shaped
  calls is 2 or even 1.

## Mechanism 2: the wave gate (batch-and-pause)

Owner's call, tested the same day. A `_WaveGate` replaces the semaphore: up to N
calls form a *wave*; once the wave is full nothing else is dispatched until every
member has returned **and** a cooldown has elapsed. The difference from a rolling
semaphore is that a semaphore refills a permit the instant any one call lands, so
it keeps N calls perpetually open and the provider never sees a moment with none of
our sockets open. Draining to zero gives the edge that window.

Configuration: `gemini_max_inflight_calls = 3`, `gemini_wave_cooldown_seconds = 2.0`
(**unmeasured** — a starting value, not a tuned one), all rate knobs off.

Live result (run started 09:51:15 UTC):

| | rolling semaphore (3) | batch-and-pause (3, 2s) |
|---|---|---|
| clean window | ~5 min | **~8.5 min** |
| first shed minute | 65 x 429 | 29 x 429 |
| peak | 107 x 429/min | 66 x 429/min |
| final tally | — | 50 x 200, 143 x 429, 12 x 503 |
| cards in clean window | 83 (over 15 min) | 29 (~220 cards/hr) |

**Better, and still the same wall.** Batch-and-pause delayed the shed by ~3.5
minutes and roughly halved its peak. It did not prevent it.

Two things the run exposed that are not about the mechanism:

1. **The queue behind the gate grew without bound.** Reported call latency climbed
   18s → 25s → 90s → 109s across the run; by 09:59 calls were waiting ~2 minutes
   for a slot. The pipeline dispatches far more work than any concurrency-3 gate
   can pass, and nothing pushes back on the fan-out. (The reported figure conflated
   queue wait with round trip — a measurement bug, now fixed: `latency` and
   `queued` are logged separately.)
2. **A bare 429 has no backoff.** ADR-0086's perimeter backoff was removed in
   favour of "park the cell 0s, take the next cell". A 429 returns in ~70ms, so the
   wave drains instantly and reopens — **143 x 429 in 2.5 minutes, ~66/min.** Per
   the transient-penalty finding above, that is precisely the behaviour that
   re-arms the IP penalty. The run was stopped for this reason.

Also observed: 12 x `503 Service Unavailable`, all on the top two generator rungs
(`gemini-3.8-flash` x6, `3.7-flash` x5) while `gemini-3.5-flash-lite` went 14/14.
That is provider-side capacity on the strong models, **not** our throttle — a
different fact from a 429, and the ladder falling to a rung that answers is it
working correctly.

## Throughput reality

- `inflight_sweep` at N=3: 1.11 good calls/s — but those are ~2.5s bare calls.
- Pipeline structured calls are 7–17s, so 3/7 is about **0.43 calls/s ≈ 340–450
  cards/hr**, which matches both measured runs (338 and ~220).
- Current corpus for scale: 41 topics, 447 subtopics, 5,491 cards, 1,665 questions;
  784 cards created on 2026-09-04 across all of the day's runs.

Faster is not a pacing problem. Under a fixed concurrency ceiling the levers are
orthogonal to pacing entirely:

1. **Fewer calls per card** (currently ~3.4 — bigger batches, batch-wide
   verification instead of per-card).
2. **Local generation** — [ADR-0008](../adr/0008-local-gpu-generation.md); an
   RTX 5070 (12 GB) running Granite 4.1 8B / Qwen3-8B for structured output with
   the per-topic RAG context prefix-cached. **The decisive test — draft ~20 cards
   locally, push them through the existing Gemini gate, compare accept rate — has
   not been run.** That single number decides viability.
3. **More egress IPs** — each IP gets its own concurrency-3 budget. The only lever
   that raises the ceiling rather than living under it.
4. **A different provider** — [document 5](05-what-we-learned.md).
