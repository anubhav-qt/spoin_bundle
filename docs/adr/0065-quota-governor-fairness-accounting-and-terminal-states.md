# ADR-0065: The quota governor spreads load, refunds refused calls, learns its own rpm, and names why it stopped

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Anubhav
- **Amends:** [ADR-0028](0028-key-model-quota-ladder.md) (key ordering within a rung),
  [ADR-0058](0058-per-minute-vs-per-day-429.md) (reverses its deliberate throttle
  over-count; extends its shared-state posture to model availability),
  [ADR-0056](0056-generation-call-timeout-and-recovery-probe.md) (the probe's exclusion is
  now persisted with an expiry)

## Context

A generation run stopped with `QuotaExhaustedError: All 33 key(s) x 4 model(s) exhausted`
and was written up as having spent the day's budget. The ledger said otherwise. Four
independent defects, each individually survivable, compounded into that one misleading
sentence.

**1. `acquire()` was first-fit from key 0.** For each rung it scanned
`range(key_count)` and returned the lowest-numbered key that was neither RPD-exhausted
nor cooling. There was no cursor, so the scan restarted at 0 every time. Whichever low
key came off cooldown first won the next grant, and the loop `return`ed before its
counter ever reached the rest of the pool. Measured on the live ledger, generator pool,
`gemini-3.5-flash-lite`: key 0 at **380**/500, key 1 at 239, key 2 at 198, and **keys
10–32 at 10–15 each with `updated_at` frozen at 16:15** — granted once apiece during one
early burst, then never revisited for two hours. The thinking pool never reached key 10
at all, which the ledger proves directly: `_ledger_row` created a row for any cell the
scan so much as looked at, and those keys have no rows.

**2. Every per-minute 429 permanently burned a day of RPD.** `acquire()` bills
`requests_spent += 1` when it grants a cell. A throttled call's retry `continue`s and
re-acquires — a different cell, another +1 — and the send was `confirmed`, so
`prune_request_window`'s phantom refund correctly declined to give it back. **727
throttles inside 16 minutes, every one a permanent RPD unit spent on zero output**, on a
thinking ladder whose entire budget is 20 per cell. ADR-0058 knew about this over-count
and accepted it deliberately, because ledger erosion was the only thing terminating the
throttle-retry loop: that branch retries without burning a cell, so something had to
bound it, and a cell walking toward its own ceiling did.

**3. The configured `rpm` was treated as fact.** 33 keys × rpm 15 = 495 requests/minute
offered, and **77% came back 429**, all with `quotaIds=(none)`. ADR-0028 assumes each key
is its own Google project; a 77% rejection rate is that assumption being wrong out loud,
whether because keys share projects, or because the documented ceiling isn't the enforced
one. The governor had no way to notice — it re-offered the same rate and collected the
same refusals.

**4. `QuotaExhaustedError` meant three unrelated things.** One raise site fired when every
cell was RPD-spent, when every cell was merely cooling, and when every rung had been
excluded as unavailable. That third case is what actually happened: `gemini-3.7-flash`
was returning `504 DEADLINE_EXCEEDED` all afternoon and had been `exclude_model`'d, so the
ladder collapsed onto rungs the earlier runs had already spent — and the error asserted a
verdict about a daily budget it had never consulted.

## Decision

### Least-spent-first within a rung

`_acquire_locked` orders keys by `requests_spent` ascending (ties broken by index, so the
choice stays deterministic), via one batched `_rung_spend` query per rung instead of
`key_count` row reads. A key with no row sorts as 0, which is both true and the ordering
we want — an untouched key is the emptiest one there is.

**The rung-before-rung property of ADR-0028 is untouched.** A ladder still drains every
key on a model before falling to the next; only the order *within* the rung changes.

This makes skew self-correcting instead of self-reinforcing, and it balances across
*processes* — the API and the worker read the same ledger, so neither has to know the
other exists to stop colliding with it.

Ledger rows are now created **only when a cell is actually granted**, not when the scan
passes over it. That keeps "a row exists" meaning "this cell was used", which is the
property that made defect 1 provable from the ledger alone.

### A refused call is refunded

`mark_rate_limited` now decrements `requests_spent` (floored at 0, clearing `exhausted_at`
if the cell drops back below its ceiling). The provider does not count a request it
refused, so neither do we.

This directly reverses ADR-0058's accepted over-count, which is only safe because the
retry loop gets a new terminator:

**`_invoke_with_retry` counts floored throttles, not all throttles.** A 429 on a cell we
had not yet slowed down is evidence our *pacing* was wrong, and the answer is to slow down
and carry on — that is the mechanism working. A 429 on a cell already at one request per
minute has no such answer. `grid_size` (`key_count × len(ladder)`) of *those* in a row,
with no success in between, means every cell refused us at the slowest pace we have. Any
success resets the count. This is a measured condition about the provider, not an invented
retry cap.

### Adaptive rpm (AIMD)

Each `(key, model)` cell carries a learned effective rpm: **halved on a per-minute 429**,
**+1 per successful call**, floored at 1, capped at the configured `rung.rpm`.
`_try_reserve_rpm` compares against that instead of the configured number.

Halving rather than stepping down one at a time because we do not know how far wrong we
are; overshooting downward costs a little latency, while creeping down keeps paying the
same 429 the whole way. The cap means the measurement can only ever explain why the
documented ceiling is too *high* — never grounds for exceeding it.

This subsumes the "are these keys really separate projects?" question rather than
answering it: whatever the real ceiling is and whatever the reason, the governor converges
on it instead of arguing with it 429 at a time. Kept in memory, unlike the window itself —
it changes on nearly every call and re-converges within a minute of traffic, and the shared
`QuotaRequest` window is still what actually *enforces* the ceiling; this only decides how
eagerly each process walks toward it.

### Three terminal states, named

`QuotaExhaustedError` becomes an abstract base (still caught by the worker's requeue path,
which is unchanged) with three subclasses:

| | Meaning | Resolves when |
|---|---|---|
| `DailyQuotaExhaustedError` | every cell has spent its RPD | the daily reset |
| `AllCellsThrottledError` | every cell refused us at the rpm floor; daily budget intact | minutes |
| `AllModelsUnavailableError` | every rung excluded as unavailable; the ledger was never consulted | the provider recovers |

`acquire()` distinguishes the first from the third by whether any rung was ever *checked*,
and the daily message names any rungs it skipped rather than silently counting them as
exhausted. `worker/__main__.py` and `scan_and_generate.py` record which one paused a run —
the requeue is identical, so the distinction lives in the log and in
`GenerationJob.last_error`, where the next person reading a stalled queue needs it.

This is CLAUDE.md's "a failed outcome and a rejected outcome are never the same number",
one level down: a provider outage and a spent budget are different facts about the world.

### Model availability is shared state

`exclude_model`/`include_model` move from an in-memory `set` per `QuotaGovernor` to a
`model_unavailable` row (migration `d1a93f6b25e7`), for exactly the reason ADR-0058 moved
the RPM window: the API process, the worker process, and both pools within each held
separate views, so a 504 outage on a model both ladders list was rediscovered up to four
times over, each rediscovery costing a full request timeout.

Rows carry an `expires_at` set to the **caller's probe budget** — a derived value, not an
independent knob. The probe that owns the row is given a fixed window to reach a verdict,
so an exclusion outliving that window is evidence the prober died (a short-lived worker
pass exiting mid-probe is the normal case, per `_probe_model`'s own docstring), not
evidence the model is still down. Without it, one crashed process could park a model for
every other process indefinitely. `prune_request_window` sweeps expired rows alongside the
request window.

## Consequences

**Easier**

- The key pool is actually used. Nominal thinking capacity (33 × 4 × 20 = 2,640 calls/day)
  stops being fiction bounded by whatever handful of low keys the scan kept returning.
- Throttling costs latency instead of daily budget. The 727-throttle burst above would now
  cost ~0 RPD rather than 727.
- The governor self-tunes to the provider's real rate limit, including limits nobody has
  documented and limits that change.
- A run report can no longer say "quota exhausted" about an outage, because the exception
  that produces that sentence is no longer reachable from that condition.
- One process discovering a dead model spares every other process the timeout.

**Harder**

- **One more query per `acquire()`** (`_rung_spend` per rung, plus the availability read).
  Offset in part by no longer reading `key_count` ledger rows one at a time, but it is a
  real addition on the hot path.
- **Least-spent ordering makes cell locality worse.** Consecutive calls now land on
  different keys by design, so any per-cell warmth (connection reuse in the cached
  `ChatGoogleGenerativeAI` clients) is spread thinner. Judged clearly worth it against
  leaving two thirds of the pool idle.
- **AIMD is in-memory, so two processes can hold different beliefs** about the same cell's
  pace. Bounded by the shared window doing the real enforcement, but it means the observed
  send rate is not exactly reconstructable from either process's logs alone.
- **The floored-throttle streak can, in principle, run long before it fires.** On a 33×4
  grid it needs 132 floored throttles in a row, each behind its own cooldown. That is the
  price of terminating on evidence rather than on a number, and it is only reachable in a
  genuine total-refusal state.
- **A new table and a migration** on a schema that had been stable — plus the operational
  step of applying it before the next run.

## Alternatives considered

- **Round-robin cursor instead of least-spent.** Two lines and no extra query. Rejected:
  it does not *rebalance* — key 0 at 380 and key 20 at 15 stay that way, it just stops
  making it worse — and each process keeps its own cursor, so the API and the worker can
  still collide on the same key. Least-spent gets cross-process balance for free by
  reading state they already share.
- **Random start offset.** Stateless and decorrelates processes. Rejected as strictly
  weaker than least-spent on evenness, for the same cost.
- **Verify the key→project mapping and group shared-project keys.** The direct answer to
  defect 3 if keys do share projects, and cheap to check. Deferred rather than rejected:
  AIMD converges on the true ceiling whatever its cause, including causes the mapping
  would not explain. Worth doing as diagnosis; no longer load-bearing as a fix.
- **Bill RPD at send time rather than at grant.** Cleaner semantics — billing would track
  reality instead of intent. Rejected for blast radius: it moves the charge across
  ADR-0061's phantom-refund logic and the `confirmed`/unconfirmed invariant, for the same
  end state the refund reaches with a smaller change.
- **Keep the over-count and just log it separately.** Zero risk, honest reporting, recovers
  no quota. Rejected: the over-count is the largest single source of wasted daily budget
  measured here.
- **A fixed retry cap on throttles.** The obvious replacement terminator. Rejected on this
  repo's own rule that a cap is a number with no principled value: the floored-throttle
  streak detects the actual condition ("nothing serves us at any pace") instead of
  guessing when to stop asking.
- **Leave `QuotaExhaustedError` as one class and improve its message.** Rejected: callers
  need to *branch* on this (a scan that stops "for tomorrow" over a five-minute outage is
  wrong), and a message is not something a caller can branch on.

## Revisit when

- The extra per-`acquire()` queries show up in generation wall-clock — the ordering could
  move to a cached per-rung snapshot refreshed every N grants rather than read every time.
- Two processes' AIMD beliefs diverge enough to matter (visible as one process throttling
  steadily while the other reports none) — that is the signal to persist the learned rpm
  the way ADR-0058 persisted the window.
- The key→project mapping gets verified either way. If keys DO share projects, the grid's
  shape is wrong at a level AIMD only compensates for, and `QuotaGovernor` should group
  keys by project rather than treat 33 keys as 33 independent ceilings.
- `AllCellsThrottledError` starts appearing in real runs. It is meant to be rare; if it is
  not, the free tier is no longer sufficient for the generation volume and that is an
  ADR-0003 question, not a governor one.
