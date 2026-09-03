# ADR-0086: Concurrency staggering and initial dispatch jitter to stop edge gateway shedding

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Anubhav, agent session
- **Amends:** [ADR-0084](0084-per-box-load-balancer.md) (adds pool-wide dispatch
  staggering to per-cell pacing), [ADR-0085](0085-tokens-are-metered-too.md)
  (complements prompt token packing with perimeter arrival spacing).

## Context

Benchmarks 1 through 7 of the ADR-0084 load balancer consistently failed in an
84%–95% 429 band. Crucially, the errors arrived as bare `RESOURCE_EXHAUSTED`
envelopes with no `details`, no `QuotaFailure`, and no `quotaId`.

The 2026-09-04 3-round isolation experiment ([handoff writeup](../handoff/adr-0085-concurrency-burst-benchmarks.md))
characterized this behavior decisively:

1. **Distinct key count is not the trigger:** 20 distinct keys fired simultaneously
   with a tiny prompt (~7 tokens) produced **0.0% bare 429s (0 / 60)** across all 3 rounds.
2. **Single keys trigger it too:** 20 concurrent calls to 1 single key with a heavy
   prompt (~10k tokens each) produced bare 429s (6.7%) alongside standard 15 RPM
   quota failures (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`).
3. **It is edge gateway load shedding:** Rejections arrive with **0.88s–1.45s latency**,
   dropped at Google's network perimeter before reaching model execution or per-project
   quota accounting.
4. **Initial fanout is an instantaneous perimeter storm:** When `resolve_and_plan_topic`
   fans out across ~15–35 subtopic groups, or when `gate_and_persist` fans out across
   tiers, all coroutines call `LoadBalancer.assign()` at the exact same millisecond.
   Because every cell in a fresh box starts with `last_send = 0.0`, all branches obtain
   reservations simultaneously with `wait = 0`. They all acquire their respective
   `cell_lock`s (which do not contend with each other) and land on Google's edge at the
   exact same instant.

ADR-0085's `pack_by_tokens` addressed the weight of individual requests. However,
if 20–35 heavy requests hit the perimeter at $t = 0.000\text{s}$, the edge gateway
sheds 10%–25% of them immediately.

## Decision

We introduce two complementary pacing mechanisms to de-synchronize network arrival:

### 1. Pool-Wide Dispatch Staggering in `LoadBalancer` (`gemini_dispatch_stagger_seconds`)
- `LoadBalancer` enforces a minimum spacing between any two consecutive reservations
  across the **entire balancer** (`_dispatch_stagger_s`, default `0.5s`).
- While `gemini_send_gap_seconds` (10s) spaces requests to the *same* `(key, model)` cell,
  `gemini_dispatch_stagger_seconds` spaces requests across *different* cells.
- When multiple coroutines call `assign()` simultaneously, the first gets $t = 0$, the
  second $t = 0.5\text{s}$, the third $t = 1.0\text{s}$, etc.
- An instantaneous 30-branch fanout is converted into a smooth stream over 15 seconds.
  Because calls complete in ~2–4 seconds, in-flight concurrency at Google's edge never
  spikes beyond 3–5 concurrent connections.

### 2. Initial Fanout Jitter in `nodes.py` (`gemini_initial_dispatch_jitter_seconds`)
- Before entering `_generate_subtopic_cards`, each subtopic group branch sleeps for a
  random jitter `uniform(0.0, gemini_initial_dispatch_jitter_seconds)` (default `1.5s`).
- This prevents dozens of branches from stampeding simultaneously on balancer locks,
  database reads, or local event loops.
- Active only when `generator != "fake"` and `gemini_initial_dispatch_jitter_seconds > 0.0`,
  ensuring unit tests run in milliseconds without synthetic delays.

## Consequences

### What becomes easier
- **Edge gateway shedding is eliminated:** Connections arrive in a spaced queue rather
  than an instantaneous burst, keeping concurrent in-flight connections below the
  perimeter abuse threshold.
- **Fairer cell distribution:** Coroutines arrive staggered at `assign()`, so least-spent
  selection and token-window checks see accurate in-flight state rather than racing
  the same cold ledger snapshot.
- **Sustained throughput:** At a 0.5s stagger, the pool can dispatch up to 120 calls/minute.
  For a 34-key or 75-key box, this comfortably accommodates the required throughput
  without artificial bottlenecking.

### What becomes harder / Costs
- Initial topic fanout is slightly less bursty, taking ~10–15s for all branches to launch
  their first call instead of launching all 30 at $t = 0$. This 10s difference is
  negligible against a multi-minute generation run and prevents the cascading 60s
  starvation cooldowns caused by 429 storms.
- Requires maintaining one additional timestamp (`_last_pool_send`) on `LoadBalancer`.

## Alternatives considered

**Rely solely on per-cell send gap (`gemini_send_gap_seconds`).**
Rejected: As demonstrated by Probe A in Benchmarks 3 and 4, per-cell spacing was already
p50 49.5s. But because all cells were cold at start, all cells dispatched their first call
at the exact same instant, triggering perimeter 429s.

**Global token semaphore across all in-flight calls.**
Rejected: A token semaphore requires predicting the exact in-flight duration of external
network calls and introduces distributed coordination overhead. Dispatch staggering is
simpler, deterministic, and addresses the actual trigger: simultaneous connection arrivals.

**Hard concurrency limit (e.g. `asyncio.Semaphore(5)`).**
Rejected: A hard semaphore caps concurrency arbitrarily regardless of pool size. Staggering
spaces the arrival rate on the wire while allowing natural in-flight overlap as responses
return.

## Revisit when

- Google publishes explicit perimeter concurrency and burst limits for the Gemini API.
- The pool size scales past 300 keys where a 0.5s dispatch stagger becomes the binding
  throughput constraint (at which point stagger can be tuned down to 0.2s or sharded).
