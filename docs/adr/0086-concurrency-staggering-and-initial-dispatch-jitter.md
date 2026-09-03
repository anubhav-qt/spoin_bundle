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
  across the **entire balancer** (`_dispatch_stagger_s`, tuned to `1.2s` following Benchmark 8).
- While `gemini_send_gap_seconds` (10s) spaces requests to the *same* `(key, model)` cell,
  `gemini_dispatch_stagger_seconds` spaces requests across *different* cells.
- Initial testing with `0.5s` in Benchmark 8 proved the fanout mechanism (45/50 calls
  in the initial wave succeeded with 200 OK), but when prompts jumped from ~4,900 chars
  to ~13,700 chars during drafting, average call latency rose to ~8s. A 0.5s stagger
  allowed in-flight concurrency to build to 16–20 simultaneous heavy calls, tripping
  Google's edge shedding. Widening to `1.2s` caps concurrent in-flight connections to
  $\sim 5\text{--}6$, safely under the edge threshold.

### 2. Initial Fanout Jitter in `nodes.py` (`gemini_initial_dispatch_jitter_seconds`)
- Before entering `_generate_subtopic_cards`, each subtopic group branch sleeps for a
  random jitter `uniform(0.5, gemini_initial_dispatch_jitter_seconds)` (default `3.5s`).
- The 0.5s floor prevents branches from firing at $t \approx 0$, while the 3.5s ceiling
  disperses 25–35 subtopics across 3 full seconds (1 arrival every ~100–140ms), joining
  the balancer's 1.2s stagger queue smoothly. Active only when `generator != "fake"`.

### 3. Perimeter Shedding Backoff in `_invoke_with_retry`
- In Benchmark 8, when Google shed a heavy payload with a bare 429, the retry loop
  in `_invoke_with_retry` immediately tried the next cell in the box with no delay.
  With 74 other keys available, it machine-gunned 148 cells in under 2 minutes.
- When an un-scoped/bare 429 arrives, the caller now pauses for `5.0s + random.uniform(0.5, 3.5s)`
  before requesting the next cell from the balancer. This decorrelated backoff gives
  the gateway perimeter window time to drain and prevents retrying coroutines from
  synchronizing their next attempts.

### 4. Inter-Round Drafting Jitter in `nodes.py`
- In `_generate_subtopic_cards`, subtopics that finish planning simultaneously can
  re-cluster on subsequent rounds. An inter-round jitter `random.uniform(0.5, 3.0s)`
  spaces out subsequent drafting rounds (rounds 2, 3, 4).

## Consequences

### What becomes easier
- **Edge gateway shedding is eliminated:** Connections arrive in a spaced queue rather
  than an instantaneous burst, keeping concurrent in-flight connections below the
  perimeter abuse threshold.
- **Fairer cell distribution:** Coroutines arrive staggered at `assign()`, so least-spent
  selection and token-window checks see accurate in-flight state rather than racing
  the same cold ledger snapshot.
- **Cascades are stopped cold:** A transient edge drop pauses that branch for 5–7s instead
  of burning through all 148 cells in the box.
- **Sustained throughput:** At a 1.2s stagger, the box dispatches 50 calls/minute,
  comfortably sustaining generation without artificial bottlenecks.

### What becomes harder / Costs
- Initial topic fanout and subsequent rounds are slightly spaced out. This ~15–30s
  difference across a multi-minute run is negligible and eliminates cascading failures.
- Requires maintaining one additional timestamp (`_last_pool_send`) on `LoadBalancer`.

## Alternatives considered

**Rely solely on per-cell send gap (`gemini_send_gap_seconds`).**
Rejected: As demonstrated by Probe A in Benchmarks 3 and 4, per-cell spacing was already
p50 49.5s. But because all cells were cold at start, all cells dispatched their first call
at the exact same instant, triggering perimeter 429s.

**Immediate cell hopping without perimeter backoff.**
Rejected: Benchmark 8 proved that rotating to the next cell 0.5s after an edge drop
exacerbates perimeter load, cascading across all 148 cells in under 2 minutes.

**Global token semaphore across all in-flight calls.**
Rejected: A token semaphore requires predicting the exact in-flight duration of external
network calls and introduces distributed coordination overhead. Dispatch staggering is
simpler, deterministic, and addresses the actual trigger: simultaneous connection arrivals.

## Revisit when

- Google publishes explicit perimeter concurrency and burst limits for the Gemini API.
- The pool size scales past 300 keys where a 1.2s dispatch stagger becomes the binding
  throughput constraint.
