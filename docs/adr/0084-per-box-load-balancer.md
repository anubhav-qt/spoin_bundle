# ADR-0084: A per-box in-memory load balancer replaces the DB-backed quota governor

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** Anubhav

- **Supersedes:** [ADR-0058](0058-per-minute-vs-per-day-429.md) (the RPM window
  moves back into memory), [ADR-0060](0060-unknown-429-scope-defaults-to-per-minute.md)
  and [ADR-0061](0061-refund-grants-that-never-became-requests.md) (both were
  about the `QuotaRequest` table, which is deleted), and the AIMD half of
  [ADR-0065](0065-quota-governor-fairness-accounting-and-terminal-states.md).
- **Amends:** [ADR-0028](0028-key-model-quota-ladder.md) (the ladder is now
  walked by a per-box balancer, not a global governor),
  [ADR-0082](0082-fixed-key-boxes-per-topic.md) and
  [ADR-0083](0083-least-spent-load-balancing-within-a-box.md) (the box now *owns*
  a balancer object; least-spent-first and no-pin are how that balancer picks).
- **Keeps:** the *idea* of [ADR-0082](0082-fixed-key-boxes-per-topic.md)'s fixed
  boxes, [ADR-0040](0040-per-cell-call-serialization.md)'s per-cell send lock,
  the three `QuotaExhaustedError` subclasses, and a `QuotaLedger` trimmed to one
  column. Nothing else from the old governor survives — see below.

## This is a removal, not a refactor

`quota.py`'s `QuotaGovernor`, `KeyClaimRegistry`, `KeyClaim`, `_ClaimWait`,
`_CellAttempt`, the AIMD `_effective_rpm` machinery, `_try_reserve_rpm`, the
probe accounting, and the `sticky`/`box`/`pool` `key_scope` plumbing in
`langchain_impl.py` are **deleted**, along with the `quota_request` and
`model_unavailable` tables and two `quota_ledger` columns. The prior design was
built and extended incrementally by AI across ten ADRs — each change locally
reasonable, the whole never sketched by a person — until the central assumption
it was all bracing against (several processes on one key pool) no longer matched
how anything runs. The replacement is a single from-scratch design. No part of
the old one is retained for compatibility or for the reasoning it encodes; the
reasoning that still applies is restated here.

## Context

The quota governor is the most-revised component in the project (ADRs 0028,
0040, 0047, 0056, 0058, 0060, 0061, 0065, 0074, 0082, 0083). Every revision
added a mechanism to a design whose central assumption — **multiple processes
draw on the key pool at once** (the API doing topic-matching and quiz-grading,
the worker generating, potentially replicas) — forced everything correctness-
critical into Postgres: the per-minute window (`QuotaRequest`), the model-
unavailable set (`ModelUnavailable`), the per-day count and cooldown
(`QuotaLedger`). A DB round-trip on the hot path, an atomic `INSERT … SELECT …
WHERE count < rpm` to make the reservation race-free, an opportunistic prune
sweep, a phantom-refund grace period.

**That assumption no longer holds for how generation actually runs.** The worker
runs one pass at a time (ADR-0073 lineage), the pipeline is the only thing
generating, and the API's own LLM calls (topic match, grade) are sparse and can
be given their own keys. With a single process on the pool, the DB machinery is
paying a permanent cost — latency, write volume, code surface — to solve a
concurrency problem that isn't there.

The owner's call: **assume one process. Move the balancer into memory, one per
box, and make it simple.**

## Decision

### 1. `LoadBalancer` — one per box, plus one for the claim-less remainder

A `LoadBalancer` owns a set of key indices and both model ladders (generator +
thinking). It holds, per `(key, model)` cell, entirely in memory:

| field | seed | update |
|---|---|---|
| `rpd_spent: int` | `QuotaLedger.requests_spent` for today, read **once** at construction (one query for the whole box) | `+1` on every success; **write-through** to `QuotaLedger` (best-effort, off the hot path) so a crash-resume re-seeds accurately |
| `rpd_limit: int` | `rung.rpd` | — |
| `window: deque[float]` | empty | append monotonic `now` on reserve; `popleft` entries older than 60 s on every read |
| `learned_rpm: float` | `rung.rpm` | `min(learned_rpm, len(window))` on a 429; `+1` per 60 s with no 429; clamp `[1, rung.rpm]`; **reset to `rung.rpm` at day rollover** |
| `cooldown_until: float` | `0` | `now + 60` (or provider `RetryInfo`) on a per-minute 429 |

Model-unavailability (503/504) is a single process-global `dict[str, float]`
(model → monotonic expiry) on `GeminiContentGenerator`, passed by reference into
every balancer — a model being down is global, not per-box. The
`model_unavailable` table is dropped; a crashed process simply loses its
exclusions, which fails toward availability and is fine.

**`QuotaLedger` is trimmed to `(day, backend, requests_spent)`.** It exists for
exactly one job now — surviving a per-day count across the many passes a day
contains, so a resume doesn't re-spend budget. `cooldown_until` and
`exhausted_at` are dropped: cooldown is a 60-second in-memory fact and the
balancer never re-reads it, and "exhausted" is just `rpd_spent >= rpd_limit`.

**Two balancer scopes:**

- **Per box.** `run_generation_pipeline` builds one when it leases a box, over
  that box's keys, and releases it with the box. Box key-subsets are handed out
  by a thin `BoxPool` allocator (owns the 75 indices, leases disjoint slices,
  fills coldest-first from the ledger) — all that survives of
  `KeyClaimRegistry`, minus the claim/pin half that ADR-0083 already made dead.
- **The remainder.** One balancer over the unboxed keys (7 at 75/34), for the
  claim-less path: `generate_curriculum`, `match_topics`, `validate_topic_names`,
  quiz grading, the recovery probe. This is ADR-0082's "remainder serves the
  claim-less path", made literal — those calls never touch a box's keys and a
  box never touches theirs, so no cross-balancer cell coordination is needed.

### 2. `assign(kind)` — pick a cell, or wait

Under the box's single `asyncio.Lock`:

1. Walk the `kind` ladder (generator or thinking) best rung first, skipping
   models in the global unavailable dict.
2. Within a rung, candidate cells = box keys where `now ≥ cooldown_until`,
   `rpd_spent < rpd_limit`, and `len(window in last 60 s) < learned_rpm`.
3. Pick the candidate with the least `rpd_spent` (tiebreak: least window
   occupancy, then key index) — ADR-0065's least-spent-first, ADR-0083's no-pin,
   now a pure in-memory sort.
4. Append `now` to that cell's `window` (the reservation) and return
   `(key, model)`.
5. Nothing anywhere: return the soonest-free wait — `min` over cooldown
   expiries and "oldest window entry + 60 s". Caller sleeps that long (capped),
   `assign` retries.

Terminal conditions raise the **existing** subclasses (`langchain_impl` and the
worker branch on them):

- every cell `rpd_spent ≥ rpd_limit` → `DailyQuotaExhaustedError`
- cells have RPD budget but all are cooling, and have been for a measured
  streak → `AllCellsThrottledError`
- every rung is in the unavailable dict → `AllModelsUnavailableError`

### 3. The send path is unchanged in shape

`assign()` returns immediately; the caller takes the per-cell `asyncio.Lock`
(kept from ADR-0040), calls `note_send(cell, now)` to move the reservation
timestamp to the true send time (ADR-0058's alignment fix, now an in-memory
`deque` edit instead of a row update), fires the HTTP call, then reports back:

- `on_success(cell)` — `rpd_spent += 1`, schedule the ledger write-through,
  maybe probe `learned_rpm` up.
- `on_rate_limited(cell, *, per_minute, retry_after)` — per-minute: set
  `cooldown_until`, `learned_rpm = min(learned_rpm, len(window))`, keep the
  window entry (the request *was* sent). per-day: mark the cell
  `rpd_spent = rpd_limit`.
- `on_send_aborted(cell)` — a timeout/exception *before* the request left:
  `popleft` the reservation (ADR-0061's refund, now trivial).
- `exclude_model(model, expiry)` — write the global dict; the recovery probe
  clears it.

### 4. Cold start — the warm-up window

A freshly built balancer has an empty `window` but its `rpd_spent` seed may
reflect spend from seconds ago whose *timing* it can't know. So every balancer
treats **all** cells as cooling until `created_at + 60 s`. That single guard
covers both cases the ADR first split apart: a second box created moments after
the first still cannot send for a full window, so the two never co-burst on a
shared belief; and a crash-restart of an in-progress box, whose in-memory window
is gone but whose keys were hot a moment ago, waits out the minute before
resuming. No explicit "space box starts 60 s apart" step is needed —
`run_generation_pipeline` leases boxes back to back and the warm-up does the
spacing.

### 5. No reserve rung

The old `reserve_rungs` (hold the last N thinking models back until every
ordinary rung is RPD-spent) is gone. Model-major assignment already does its
job: `try_assign` always prefers the strongest rung that has *any* capacity, so
a weaker model is only reached when the stronger ones are genuinely spent for
the day. The one thing the reserve added beyond that — refusing rung N even
while rungs 1..N-1 are momentarily *throttled* — is not worth a special case; a
transient all-strong-rungs-cooling window is rare and self-corrects within
seconds. `gemini_thinking_reserve_rungs` stays in `Settings` (unused) rather
than churning the config surface.

### 6. Assume no shared projects

Per the key audit's end state (one key per distinct GCP project kept, plus the
33 verified-separate), the 75-key pool is treated as 75 independent per-minute
buckets. If that stops being true, `learned_rpm`'s `min(…, len(window))` still
converges to a safe state (two keys in one bucket drive each other's ceiling
down until the sum fits) — just less efficiently than knowing the grouping.

## Consequences

**Easier**

- **No DB on the quota hot path.** `assign()` is an in-memory sort under a lock.
  `QuotaRequest` (a write per grant + a write per send + a prune sweep per
  acquire) is gone.
- **One mechanism.** No `sticky`/`box`/`pool` `key_scope`, no global governor +
  per-box narrowing — a box *is* its balancer.
- **The learning is evidence-based, not a guess.** `min(learned_rpm,
  len(window))` on a 429 lands on the measured number in one step; AIMD's blind
  halving (and ADR-0083's patch to stop it firing on scopeless 429s) both go
  away.
- **Per-box lock, not a process-global one.** Two boxes' `assign()` calls never
  serialise against each other.

**Harder / committed to**

- **Single process is now a correctness requirement, not a performance
  assumption.** If the API and the worker ever draw on the *same* keys
  concurrently, they will each permit the full ceiling and the provider will
  429 — exactly the bug ADR-0058 moved the window into Postgres to prevent. The
  claim-less remainder balancer keeps the API's *current* calls off box keys,
  but a second *generating* process would break this. Documented loudly in the
  module docstring and `generation-pipeline.md`.
- **A crash loses the RPM window.** RPD is re-seeded from the ledger write-
  through; the trailing minute is not persisted, so the warm-up (§4) is load-
  bearing, not belt-and-braces.
- **Model-unavailability doesn't survive a crash.** Fails toward availability;
  acceptable, but a flapping model will be re-probed by each fresh process.
- **The migration is destructive.** `quota_request` and `model_unavailable` are
  dropped whole; `quota_ledger` loses two columns. `downgrade()` recreates the
  structures but not the data — acceptable, since every row in them is
  worthless after 60 seconds (`quota_request`) or the next probe
  (`model_unavailable`), and the dropped ledger columns are same-day-only state.
- **~1900 lines deleted.** `quota.py` shrinks from ~1660 to a small
  `LadderRung`/`parse_ladder`/errors core plus the new balancer; the
  `key_scope` machinery leaves `langchain_impl.py`; `test_quota_governor.py`
  and `test_key_claims.py` are replaced by `test_load_balancer.py`.

## Alternatives considered

**Keep the DB-backed governor, just split the lock per box.** The smallest
change. Rejected on the owner's call — it keeps the round-trip and the
`QuotaRequest` write volume for a concurrency guarantee that a single process
doesn't need, and leaves two learning mechanisms (AIMD + ADR-0083's gate) in a
file that is already the most-revised in the repo.

**One balancer for the whole pool, boxes just filter its candidate list.**
Fewer objects. Rejected: the per-box lock is the point — a shared balancer
reintroduces one lock every `assign()` contends on, which is what ADR-0047
deleted a semaphore to escape.

**Persist the window as a per-cell counter with a reset timestamp** (the "rotate
every 60 s from last activity" model discussed). Rejected: under continuous load
it never rotates, so it either caps at the first `rpm` requests forever or needs
a gap that generation never has. A true trailing-60 s `deque` is the
provider-aligned model and costs one `popleft` loop.

**Keep `ModelUnavailable` in the DB.** Cheap (few rows). Rejected for
consistency — if the window is in memory under the single-process assumption,
the unavailable set has the same shape and the same justification.

## Revisit when

- **A second process needs to generate.** Then the single-process assumption is
  void and the window (at least) goes back to shared storage — this ADR is
  substantially reversed. The `QuotaLedger` write-through and the three error
  subclasses are the parts that survive.
- **A benchmark under boxes shows 429 rates materially above Run 8's.** Same
  trigger as ADR-0082/0083 — the fix is a bigger box (fewer concurrent
  balancers), or the global in-flight-rpm semaphore sitting under the boxes.
- **Cold-start bursts show up in the logs** (a fresh balancer 429-storming in
  its first minute). The warm-up window is too short, or box spacing isn't
  being honored on the CLI path.
- **`learned_rpm` for a cell sits pinned low with no matching 429s.** The
  `min(…, len(window))` decrease fired on a per-day 429 that should have marked
  the cell exhausted instead — check the 429 classification.
