# ADR-0082: A topic gets a fixed box of keys — parallel across boxes, ADR-0074 inside one

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Anubhav
- **Mechanism replaced by:** [ADR-0084](0084-per-box-load-balancer.md) -- the box arithmetic (`pool // box_size` topics, a fixed closed slice each, a reserved remainder) is unchanged. What changed underneath: a box now *owns a `LoadBalancer`* instead of narrowing a shared `QuotaGovernor`'s scans.

- **Supersedes:** [ADR-0073](0073-worker-runs-generation-jobs-sequentially.md)'s
  strictly-sequential job loop. The worker runs several jobs concurrently again
  (the `asyncio.gather` shape), bounded by how many whole key boxes the pool
  holds rather than by nothing.
- **Amends:** [ADR-0074](0074-key-per-subtopic-scheduling.md) — "any unclaimed
  key" now means *any unclaimed key in this topic's box*. ADR-0074's ladder is
  unchanged; its scope is.
- **Refined by:** [ADR-0083](0083-least-spent-load-balancing-within-a-box.md)
  (2026-09-03, the same benchmarking pass). This ADR was written expecting
  ADR-0074's per-group **key pin** to stay intact inside the box; the benchmark
  showed the pin itself concentrating a group's ~10-call burst onto one key and
  tripping its 15-rpm cell. ADR-0083 turns the pin off for generation work —
  least-spent-first *within the box* per call — and stops the learned-rpm shrink
  firing on scopeless 429s. The box (this ADR) bounds *which* keys a topic
  touches; ADR-0083 governs *how it spreads across them*. Where this ADR's prose
  says "inside the box, ADR-0074 is untouched", read: inside the box, ADR-0074
  as amended by ADR-0083 — the one-caller-per-cell guarantee is what is
  untouched, not the pin.
- **Learns from:** [ADR-0078](0078-topic-parallel-key-leases.md) (reverted the
  day it landed). Same goal — topics in parallel — with the two properties that
  made it unsafe removed: the slice size is fixed instead of derived from the
  curriculum, and there is no shared reserve to borrow from.
- **Does not touch:** [ADR-0040](0040-per-cell-call-serialization.md),
  [ADR-0028](0028-key-model-quota-ladder.md), or
  [ADR-0065](0065-quota-governor-fairness-accounting-and-terminal-states.md)'s
  accounting. `cell_lock` still guards the send; the ladder and its terminal
  states are the same, read over a smaller set of keys.

## Context

Two regimes have run on this pool, and each failed in the opposite direction.

**ADR-0073 + ADR-0074 (the Run 8 regime, and what is in `main` today).** One
topic at a time; inside it, one key per subtopic group over the *whole* pool.
Walk-away-safe — [Run 8](../architecture/generation-pipeline-run-8-benchmark.md)
generated 4,139 cards unattended — but a single topic can only ever keep as many
keys busy as it has subtopic groups in flight, so most of a 119-key pool sits
idle while one topic works through its curriculum, and a queue of six topics
takes six times as long as it needs to. (The pool is 75 keys today, not the 119
ADR-0078 was written against: the key-project audit dropped 5 dead keys, then
resolved a 45-key block down to ~6 distinct projects — one key kept per project,
the other 39 staged out — because keys sharing a GCP project share one quota.)

**ADR-0078.** Many topics at once, each leasing `N` keys where `N` was its
widest difficulty tier, plus a shared reserve any spent group could borrow from.
Reverted the same day: with a big pool the packer admitted a dozen-plus topics,
40+ subtopic branches ran at once, and the thinking rungs (rpm 5 / rpd 20) went
into sustained 429 storms and per-day exhaustion. The specific defect is worth
naming, because "it ran too many topics" is only half of it: **`N` was derived
from data, and the reserve was shared.** A curriculum with a wide tier admitted
itself a big lease; a spent group reached outside its lease for a reserve key
another topic was about to be handed. So the number of callers on the pool at
any moment was a function of what the queue happened to contain — not something
anyone could state before starting a run, and not something a benchmark could
establish once.

The owner's ask is the middle: keep a topic's internals exactly as they are —
that part is proven — and run a few of them side by side.

## Decision

**A topic gets a BOX: `settings.topic_key_box_size` keys (34 today, 2 boxes of a
75-key pool), for its
whole run, and that box is its entire key pool.** Inside the box, ADR-0074 is
untouched. Outside it, nothing exists.

### 1. `pool // box_size` topics per pass, and no other number

`Settings.max_concurrent_topics` is `gemini_pool_size // topic_key_box_size` —
2 at the current 75-key pool and a box of 34 — and `run_once()` claims exactly that many pending jobs (never
more than `generation_batch_size`) in `priority DESC, created_at` order, then
runs them with `asyncio.gather`, each on its own DB session, sharing one
`ContentGenerator` so a single `KeyClaimRegistry` keeps the boxes disjoint.

Claiming exactly what will run is deliberate: there is no admit-then-demote
step, so a row is marked `running` only when a box is about to be handed to it.
The remainder of the pool (75 - 2×34 = 7 keys) stays unboxed and serves the
lease-less path — the API's topic matching, quiz grading, the recovery probe —
which is a small win in itself: ad-hoc API calls stop competing with generation
for the same cells.

**One knob, not two.** Concurrency is derived from the box size and never
configured separately. Two numbers can disagree, and "4 topics of 35 keys out of
75" is a state no arithmetic downstream can make safe.

### 2. A box is a total pool, not a preference

For a claim inside box `B`, every scan in `_acquire_for_claim` reads `B` and only
`B`: the first bind, the move to a fresher key when the held one is spent, the
"does anything still have daily room?" test that gates the reserve rung, and the
counts in the wait log. `KeyClaimRegistry.claimable_keys` is the single place
that narrowing happens, so the property holds by construction rather than by
each scan remembering to check.

**No shared reserve, and no borrowing.** This is the direct lesson from
ADR-0078: a fallback that reaches outside the box makes the number of concurrent
callers on a key depend on how spent the *other* boxes are. With the box closed,
total in-flight work is `max_concurrent_topics × box_size` keys with one caller
each — a constant, whatever the queue contains.

A consequence worth stating: a box whose own keys are spent for the day
escalates to the reserve *rung* (`gemini-3-flash-preview`) while another box
still has ordinary budget. That is correct, not a leak — waiting on budget that
can never be handed to it is a hang, not contention. It does mean the reserve
rung can now be reached with pool-wide budget remaining; the log line is already
scoped to the claim, so it says what it means.

### 3. Boxes are filled coldest-first and released by the run

`GeminiContentGenerator.lease_key_box` sums each key's `requests_spent` across
both pools' cells for the day (`quota.key_spend_today`) and takes the
least-spent keys first — ADR-0065's principle applied to boxes. A box is held
for a whole run and a day is many passes, so first-fit from key 0 would burn the
low indices down pass after pass and leave the high ones permanently cold.

`run_generation_pipeline` takes every box before the graph runs and releases
them in a `finally`. A box's lifetime is the *run's*, not a node's: one place
takes them, one place gives them back, and a crash mid-branch cannot strand a
third of the pool until the process exits. `release_box` also drops any claim
still bound to its keys.

A box that comes back short — or empty — is not an error. The topic runs on what
it got (an empty one falls back to ADR-0074's whole-pool claim), because a topic
holding fewer keys still generates where refusing to start just idles them.

The empty-box fallback is whole-pool rather than "wait for a box", deliberately.
The only caller that can over-subscribe is the CLI (`generate_topics.py` takes
several topics in ONE pipeline run — the worker admits exactly what fits), and
there every topic's box is released at the same fan-in. A topic waiting for a box
in that shape waits for a release that its own siblings' completion cannot
trigger: a deadlock, not a queue. Over-subscribing rarely, loudly logged, is the
better failure — and it is why the worker claims by box count rather than
handing the pipeline a batch and hoping.

### 4. `fake` and local backends are unbounded by this

With no key pool to divide, `max_concurrent_topics` is `generation_batch_size`
and `lease_key_box` returns an empty box. The box exists to respect the
provider's per-minute ceilings; a backend that never calls the provider should
not inherit a limit that exists only because of them.

## Consequences

**Easier**

- **Two topics finish in the time one used to** (three or more once the pool
  grows -- the arithmetic follows the key count with no code change), with each
  topic's internal behaviour byte-for-byte the regime Run 8 validated.
- **The bound is one sentence and one number.** "A topic owns 34 keys; the pool
  holds 2 boxes." Nothing about it depends on what is in the queue, so it can be
  benchmarked once and trusted.
- **A topic's whole run shows up under a known 34 keys** in the ledger, so a
  pathological topic is attributable — and cannot poison another topic's cells.
- **The API's own calls get room of their own** in the unboxed remainder.
- **Tuning is one dial with an obvious trade.** Raise `topic_key_box_size` for
  fewer, faster topics; lower it for more, slower ones.

**Harder**

- **The remainder is not generation capacity.** 7 of 75 keys do no card work
  (it was 14 of 119 before the key audit, and will be again as the pool grows).
  Deliberate: rounding up into a fourth short box would take keys a running
  topic is entitled to, which is exactly the over-admission ADR-0078 died of.
- **A narrow topic under-uses its box.** A curriculum whose widest tier is 6
  subtopics leaves ~28 keys idle for that run. Also deliberate — lending them
  out is the shared reserve by another name.
- **A wide topic serializes its surplus.** More than 34 concurrent groups means
  group 35 waits for a sibling to release a key. A contention wait (seconds),
  not an RPD wait.
- **Topics no longer finish in request order.** ADR-0073's reason for going
  sequential — progress panels completing in the order they were added — is
  given up for throughput; two panels now advance together.
- **The reserve rung is reachable earlier**, per box rather than per pool. See
  §2; the alternative is a hang.

**Committed to**

- **A box is closed.** No borrowing, no reserve, no "just this once" reach into
  another topic's keys. If throughput demands more, the answer is a bigger pool
  or a stated change to the box size — decided here, not relaxed in code.
- **Concurrency stays derived from the box size**, never a second setting.
- **One caller per key**, ADR-0074's guarantee, unchanged.

## Alternatives considered

**Keep ADR-0073's sequential loop.** Proven walk-away-safe. Rejected: it leaves
most of the pool idle, and the owner asked for throughput against a pool that
can now afford it.

**Re-land ADR-0078 with a cap on admitted topics.** Fewer moving parts than a
new mechanism. Rejected: the cap addresses how many topics run, not the two
properties that actually broke it — a data-derived lease size and a shared
reserve. Both would still be there.

**Size the box to the topic's widest tier (ADR-0078's `N`), but cap the topic
count.** Better utilisation: a narrow topic wouldn't sit on 34 keys. Rejected on
the owner's call — a fixed box is the reason the bound is stateable in advance,
and utilisation is worth less than being able to start a run and walk away.

**Lend a box's idle keys out while it works a narrow tier.** Rejected for the
reason ADR-0078 rejected it and then reintroduced it as the reserve: the topic
has to re-acquire them (possibly losing them) when its next tier needs the
width, and a lend is a borrow seen from the other side.

**A global in-flight LLM-call semaphore sized to real aggregate RPM** (the idea
the ADR-0078 revert note left behind). Bounds concurrency directly rather than
via key ownership. Not rejected on the merits — it is orthogonal, and would sit
*under* boxes if per-minute pressure turns out to bind before per-day does. The
box is the cheaper thing to try first because it changes one scan's scope and
nothing else.

## Revisit when

- **A benchmark run under boxes shows 429 rates materially above Run 8's.** Then
  34 × 2 is still too much per-minute pressure and the box should GROW (a bigger
  box means fewer of them — the dial runs the other way from intuition).
- **A benchmark shows 429 rates unchanged.** Then the pressure has headroom and
  the box should shrink toward three or four concurrent topics.
- **Topics routinely finish with most of their box idle.** The fixed size is
  costing more than it buys; the width-derived alternative gets another look,
  this time with a topic-count cap in front of it.
- **Groups routinely wait on a box key.** Boxes are too small for real
  curricula — raise `topic_key_box_size`, accepting fewer concurrent topics.
- **The worker becomes a persistent loop** (ADR-0073's own revisit condition).
  "Keep the pool full" replaces "fit this pass", and boxes would be taken and
  returned continuously rather than per pass.
