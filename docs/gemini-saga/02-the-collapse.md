# 2. The collapse

> **2026-08-30 → 2026-09-03.** Eight consecutive benchmarks. Roughly ten hours of
> runtime. **Zero cards persisted.** Every run died inside 2–10 minutes in an
> 84–95% HTTP 429 rate, against errors that refused to say what limit they were
> about.

The source-of-truth account of this period is
[`docs/notes/rate-limit-load-balancer-debugging.md`](../notes/rate-limit-load-balancer-debugging.md).
This is the summary and, more usefully, the list of theories that were wrong.

## What changed first

Run 8 finished on 08-30 with 33 keys and a sequential topic loop. Three things then
happened in quick succession, each individually reasonable:

- **[ADR-0078](../adr/0078-topic-parallel-key-leases.md) (09-01)** — parallelize
  topics, one key lease each. **Reverted the same day.** Running many topics at once
  multiplied per-minute pressure; ~40+ concurrent subtopic branches burst the
  thinking rungs (rpm 5 / rpd 20) into sustained 429 storms. The run stopped being
  something you could start and walk away from — which had been Run 6's whole
  achievement.
- **[ADR-0082](../adr/0082-fixed-key-boxes-per-topic.md) (09-02)** — the fix for
  that: a topic gets a *fixed box* of keys. Parallel across boxes, ADR-0074 inside
  one. `pool // box_size` topics at a time, a reserved remainder for the claim-less
  path (topic matching, curriculum, grading).
- **[ADR-0084](../adr/0084-per-box-load-balancer.md) (09-03)** — the owner called
  for a from-scratch replacement of the quota governor: *"it was all AI slop"*,
  grown by accretion across ten ADRs against a multi-process assumption that no
  longer held. `quota.py` went from ~1,660 lines to ~150. The `quota_request` and
  `model_unavailable` tables were dropped; `quota_ledger` was trimmed to a single
  `requests_spent` column. A box now owns an in-memory `LoadBalancer` instead of
  narrowing a shared governor's scans.

The key pool also grew through this period — 33 → 75 → 109 keys, across separate
Google Cloud projects — on the reasoning that more cells means more headroom.

## The benchmarks

From the [Benchmark 9 handoff](../handoff/adr-0086-breakthrough-benchmark.md)'s
chronology table:

| Bench | Change | Pool | Pacing | Duration | Outcome | Cards |
|:---:|---|:---:|---|:---:|---|:---:|
| B1–B4 | Initial `LoadBalancer` + sliding window | 2 boxes of 34 | none | 3–8 min | 95% 429s, `AllCellsThrottledError`. Keys slammed simultaneously. | **0** |
| B5 | [ADR-0084](../adr/0084-per-box-load-balancer.md) send gap 4.0s | 1 box of 75 | 15 rpm/cell | 10 min | 85% 429s. Un-scoped bare 429s flooded the pool. | **0** |
| B6 | send gap 10.0s | 1 box of 75 | 6 rpm/cell | 8 min | 88% 429s. Simultaneous fan-out storm at t=0. | **0** |
| B7 | [ADR-0085](../adr/0085-tokens-are-metered-too.md) token budgets | 1 box of 75 | 16k tokens, 10s gap | 6 min | 84% 429s. Card prompts still fanned out together. | **0** |
| B8 | [ADR-0086](../adr/0086-concurrency-staggering-and-initial-dispatch-jitter.md) 0.5s stagger + 1.5s jitter | 1 box of 75 | — | 7 min | **90% success in planning**, then failed in drafting: 0.5s stagger allowed 16–20 heavy calls in flight; the retry loop machine-gunned all 148 cells without backoff. | **0** |

Benchmark 1 (`b542r0bob`) is worth singling out because its diagnosis set the tone:
a fan-out burst — ~60 subtopic groups wanting a key within the same 2 seconds —
tripped the provider regardless of the per-minute *average*, and the AIMD
learned-rpm then floored healthy keys to 1 rpm off a single burst collision. The
response (owner's call) was `gemini_send_gap_seconds = 4.0`, a hard minimum between
two sends to the same cell, with the trailing window and learned rpm shelved while
a gap is set. **The gap *is* the rate limiter.**

## The theories that were wrong

Every one of these was seriously entertained, and each cost hours:

1. **"We are hitting per-day quota."** The errors said `RESOURCE_EXHAUSTED`. But
   keys were nowhere near their daily counts, and Google's own dashboard disagreed
   — a discrepancy first seen back in
   [Run 5](../architecture/generation-pipeline-run-5-benchmark.md).
2. **"The keys share a project and therefore a quota."** They did not; keys were
   spread across separate Google Cloud projects specifically to rule this out.
3. **"Our accounting is wrong."** It partly was — ADR-0084 rewrote it, ADR-0085
   added token metering — and fixing it changed nothing. B5, B6 and B7 each fixed a
   real accounting bug and each still produced zero cards.
4. **"We are sending too fast."** The most persistent one. It generated the entire
   pacing architecture: per-cell send gaps, pool-wide dispatch staggering, initial
   fan-out jitter, inter-round jitter. Pacing *helped* (see
   [document 3](03-the-pacing-breakthrough.md)) — but B6's 6 rpm per cell is a very
   slow rate and still failed at 88%, which should have been the clue.
5. **"Some keys are poisoned."** The window-rotation experiments in
   [document 4](04-the-concurrency-ceiling.md) chased this. A failure-rate-triggered
   key rotation was built, shipped and measured: it fired 14 times in 4 minutes,
   because every window it rotated *to* spiked too.

## The isolation test that pointed the right way

Between B7 and B8 a 3-round matrix test on 20 keys compared heavy prompts against
tiny ones under otherwise identical conditions:

- **Tiny prompt → 0.0% bare 429s.**
- **Heavy prompt → 10% bare 429s.**

This was recorded at the time as "edge gateway load-shedding" and correctly
identified the *character* of the limiter — something in front of the quota system,
reacting to request weight, returning `RESOURCE_EXHAUSTED` with no scope because it
has no quota to name. What it did not yet isolate was the variable that actually
governs it. That took another day.

## The state at the end of 09-03

A pipeline that had generated 4,139 cards in a day the previous week could not
persist a single card. Ten ADRs of quota machinery, 109 API keys across separate
projects, and every knob turned toward "slower" — and it was still failing at 84%.
