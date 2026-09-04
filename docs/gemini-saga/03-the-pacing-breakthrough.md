# 3. The pacing breakthrough

> **2026-09-04, early hours.** Benchmark 9. After ten hours of zero-card runs, a
> complete end-to-end topic: **426 cards and 287 questions in 37m 48s, exit code 0.**
> Full account: [the ADR-0086 handoff](../handoff/adr-0086-breakthrough-benchmark.md).

## What was turned on

[ADR-0086](../adr/0086-concurrency-staggering-and-initial-dispatch-jitter.md) — a
four-pillar pacing architecture, arrived at by tightening B8's numbers:

| Pillar | Setting | Value |
|---|---|---|
| Per-cell send gap | `gemini_send_gap_seconds` | 10.0s (6 rpm per cell) |
| Pool-wide dispatch stagger | `gemini_dispatch_stagger_seconds` | 1.2s between *any* two reservations |
| Initial fan-out jitter | `gemini_initial_dispatch_jitter_seconds` | random 0.5–3.5s before a subtopic branch starts |
| Round jitter | (in `pipeline/nodes.py`) | random 0.5–3.0s between drafting rounds |
| Perimeter backoff | (in `langchain_impl.py`) | 5.0 + random 0.5–3.5s on a bare 429 |

## The result

- **37m 48s**, exit code 0, no crashes, no unhandled exceptions.
- **426 cards** accepted (19 rejected by the gate, 3 failed), taking the
  *Generative AI* topic from 138 → 564 active cards, 97.6% of its 578-card target.
- **287 questions**, 0 rejected.
- **~676 cards/hr, ~1,131 total items/hr** on a single box of keys.

Measured against Run 8's 22–32 cards/min this is slower, but Run 8 was the old
world; measured against the previous ten hours it was infinite improvement.

## Why the win was narrower than it looked

The handoff called it a breakthrough, and for the immediate purpose it was. But
read the pillars again and notice what they have in common: **every one of them is
a rate control.** Send gap, stagger, jitter, backoff — four different ways of
spacing out *when* requests are dispatched.

None of them directly bounds **how many requests are open at the same time.**

They bound it *indirectly*, and that is the whole subtlety. A 1.2s stagger with
~7s calls yields roughly 7/1.2 ≈ 6 requests in flight; the handoff notes B9 ran at
"~5–6 calls in flight". That number is a *consequence* of the stagger and the call
latency, not something the system controls — so it drifts whenever latency drifts.
When calls get slower, in-flight silently rises. When a phase transition changes
the mix of call sizes, it rises again.

So Benchmark 9 succeeded by accidentally landing near the right in-flight number
via a rate knob, without anyone knowing that in-flight was the variable that
mattered. The very next run demonstrated the fragility:

**Benchmark 10** tried 34-key boxes × 3 concurrent topics — a pure *parallelism*
increase, with the same pacing settings — and produced **0 cards in 3 minutes.**
Topic-level parallelism multiplies arrival rate against a ceiling that was already
binding, and the classification bug described in
[document 4](04-the-concurrency-ceiling.md) then liquidated 136 of 204 generator
cells in 60 seconds.

The pacing architecture was a working proxy for the real control. Document 4 is
about finding the thing it was a proxy *for*.
