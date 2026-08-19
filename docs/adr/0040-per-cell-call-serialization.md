# ADR-0040: Serialize actual network calls per (key, model) cell

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** Anubhav
- **Revisit condition met from:** [ADR-0028](0028-key-model-quota-ladder.md) — "A second
  process... needs to share a key concurrently" was the anticipated trigger; what actually
  hit was concurrency *within* one process, a gap that ADR didn't cover.

## Context

Running `generate_topics` for two topics (and later for one topic alone) produced real 429s
from the Gemini API on cells the local `QuotaLedger` believed had room — the exact drift
ADR-0028 flagged as a live risk, but happening far more than expected: dozens of cells,
seconds apart, well under both the configured RPD and RPM ceilings.

The cause was a gap in `QuotaGovernor.acquire()`'s contract: it grants a `(key, model)` cell
and records the RPM hit immediately, then returns — the actual HTTP call happens later, made
by the caller (`langchain_impl.py`'s `_invoke_with_retry`). Nothing stops several concurrently
running subtopic tasks (up to `max_concurrent_generation_calls`) from each acquiring a
*different* cell in the same instant and firing their HTTP calls together. Our sliding window
tracks *acquired* count, not *in-flight* count, so it saw "room" the whole time — the actual
burst pattern arriving at Google's own limiter is invisible to it.

Compounding this: `mark_exhausted()` treats any real 429 as proof the cell is genuinely spent
for the rest of the day, force-setting `requests_spent = rpd`. That's the right response to a
*real* exhaustion signal, but it also permanently poisons a cell that only 429'd because of
this burst pattern — one false 429 early in a run writes off a cell's entire daily budget,
even though the provider-side usage was nowhere near its real limit.

## Decision

Three approaches were tried in order before landing on the one kept:

1. **Lower the configured RPD/RPM ladder numbers below the real dashboard limits**, to leave
   headroom. Rejected on reflection — it doesn't touch the actual bug (calls still fire in a
   burst), just makes the burst smaller and harder to notice; wastes real, usable quota for
   no structural fix.
2. **Random jitter delay (0–10s) after a cell is granted, before the call fires.** An
   improvement — spreads departures across a window — but still probabilistic. Two calls to
   the same cell can still land close together by chance, and it does nothing to help
   *legitimately* concurrent calls to *different* cells finish sooner.
3. **Per-cell serialization: queue calls to the same `(key, model)` cell, one at a time,
   waiting for each to finish before the next fires.** This is the one kept. It directly
   matches the actual hazard — same-cell bursts — without touching the concurrency across
   *different* cells (independent quota, no reason to slow those down).

`QuotaGovernor` gained `cell_lock(key_index, model) -> asyncio.Lock`, one lock per cell,
created lazily. `_invoke_with_retry` holds this lock around the actual network call (not
around `acquire()`, which already has its own separate lock for the DB/window bookkeeping).
Same-cell calls now queue in FIFO order and wait for the prior call to complete; different
cells still run fully concurrently, so aggregate throughput across the grid is unaffected.

## Consequences

**Easier**

- The RPM ceiling in the ladder config now means what it says — a cell can't be driven over
  its configured rate by request bursts from this process's own concurrency.
- No more false 429s means `mark_exhausted()` fires only on genuine exhaustion, so a cell's
  daily budget isn't wasted by a race that had nothing to do with real usage.

**Harder**

- A cell that's mid-call now blocks a second task that wants the *same* cell — that task
  effectively waits out the first call's full round-trip (seen taking up to 30s+) before it
  can even attempt its own request. Acceptable: with 9 keys × several models per pool, tasks
  land on a shared cell rarely, and the alternative (bursting) was strictly worse.
- Doesn't address the existing gap ADR-0028 already named in "Harder": the RPM window and now
  the cell locks are both in-process only, so a second OS process (e.g. a manual CLI run
  racing the cron worker) still isn't protected.
- Today's `QuotaLedger` rows are already poisoned from before this fix landed — most cells
  show `requests_spent` forced to their RPD ceiling by a false 429, even though Google's own
  dashboard shows well under half of real daily quota used. That mismatch is now understood
  (see this session's ledger inspection) but not yet remedied; the poisoned rows persist until
  the day rolls over or someone resets them by hand.

## Alternatives considered

**Global single-flight queue (one call in flight across the ENTIRE grid, not per cell).**
Considered directly — simplest possible fix, guaranteed no burst. Rejected: throws away the
whole point of the multi-key grid (ADR-0028) by serializing all 9 keys' independent quota
down to the throughput of one. Per-cell locking gets the same burst-safety without that cost.

**Persist an in-flight counter to Postgres alongside RPD.** Would make the "room" check
account for calls that were granted but haven't completed yet, closing the gap more directly
than a lock. Rejected for now — same DB-round-trip-per-call cost ADR-0028 already rejected for
RPM, and the lock achieves the same practical outcome without it.

## Revisit when

- A second OS process needs to share a key concurrently with this one (still open from
  ADR-0028 — cell locks don't close it either, being in-process only).
- The poisoned ledger rows from before this fix need an actual remedy (a manual reset, or
  `mark_exhausted` softened to not force the FULL day's budget on one 429) rather than waiting
  for midnight PT rollover.
