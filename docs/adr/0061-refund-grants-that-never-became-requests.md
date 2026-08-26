# ADR-0061: The prune refunds a grant that never became a request — and only that

- **Status:** Accepted (amends [ADR-0058](0058-per-minute-vs-per-day-429.md))
- **Date:** 2026-08-26
- **Deciders:** Anubhav

## Context

`acquire()` bills a cell's daily ledger at the moment it **grants** the cell, before any
network call has been attempted. The call fires later — the caller still has to win
`cell_lock`, which queues behind every other call on that cell.

RPM already treats that gap as a correctness problem and closes it. `_try_reserve_rpm`
inserts a `QuotaRequest` with `confirmed=False` at grant time so concurrent callers can see
the pending traffic, and `note_request_sent` later moves the row to the true send time and
flips `confirmed=True`. [ADR-0058](0058-per-minute-vs-per-day-429.md) spells out why: we
would otherwise count a request in the minute it was reserved while the provider counted it
in the minute it arrived.

**RPD never got the second half of that treatment.** It is charged once, at grant, and
nothing ever reconciles it against whether a request actually left the process. Measured on
2026-08-26 against the one generator cell that survived the incident in
[ADR-0060](0060-unknown-429-scope-defaults-to-per-minute.md): our ledger read **107** where
the provider's own dashboard read **87** — a ~19% over-count, permanent for the day.

That gap has two distinct sources, and they are not the same fact:

1. **A request that reached the provider and came back 429.** Confirmed, real, and not
   counted against the provider's daily total — a rejected request consumes no quota there.
2. **A grant whose call never happened at all.** The task died between `acquire()` returning
   and the send: a cancelled `cell_lock` await, a client construction error, the process
   exiting mid-fan-out (`gate_and_persist` fans out across every subtopic-tier via
   `asyncio.gather` without `return_exceptions=True`, so a sibling raising leaves the rest
   in flight). Pure loss — the cell is billed for something that never existed.

## Decision

**The prune refunds source 2, and never source 1.**

`prune_request_window` already deletes `QuotaRequest` rows once they age past
`_REQUEST_RETENTION_SECONDS` (five minutes — five times the window it enforces). It now
reads those rows on the way out instead of discarding them blind: any still `confirmed=False`
that late is a grant that never became a request, and its cell's ledger is credited back.

The retention margin is what makes the inference sound. `note_request_sent` is the *first*
statement in `_invoke_with_backoff`, before `ainvoke`, so a real send is confirmed within
milliseconds of the attempt starting. Five minutes later, "still unconfirmed" cannot mean
"sent, slowly"; it means never sent.

**Refunds are keyed on the pruned row's own day**, not today's — retention outlives
midnight, so a run spanning it would otherwise credit yesterday's phantom against today's
fresh budget.

**A cell already marked exhausted is skipped entirely.** `mark_exhausted` retires a cell for
the day by decision; bookkeeping must not be able to walk it back under its cap and return
it to rotation.

### Why source 1 is deliberately left over-counting

This is the part that looks like an obvious second win and is actually a trap.

`_invoke_with_retry`'s per-minute branch retries **without burning a cell** — that is
ADR-0058's deliberate design, so a brief throttle cannot consume the grid's attempt budget.
The loop is therefore bounded by exactly one thing: the ledger climbing, on every
`acquire()`, until `QuotaExhaustedError`. Its own docstring says so — "bounded by real
quota: every `acquire()` increments a ledger that now only ever counts UP."

Refunding a throttled call removes that bound. The loop becomes retry → 429 → refund →
retry, forever, against a cell that never advances toward any ceiling. And
[ADR-0060](0060-unknown-429-scope-defaults-to-per-minute.md) has just widened the door into
that branch by routing *unidentifiable* 429s down it too.

So the over-count from a rejected send stays. It is conservative (we under-use rather than
over-run the provider), it is what ADR-0058 knowingly accepted in its "Harder" section, and
it is load-bearing for termination. A test pins it (`test_prune_never_refunds_a_confirmed_send`)
with the reasoning attached, because it reads like a leak to plug and must not be.

## Consequences

**Easier.** `quota_ledger.requests_spent` converges on what the provider actually saw, minus
only the deliberate throttle margin — so it can be trusted to answer "how much is left
today?" without cross-checking a dashboard. Long or interrupted runs no longer bleed
capacity permanently; the phantoms clear themselves within five minutes of being stranded.
A refund is logged, so the correction is visible rather than silent.

**Harder.** `prune_request_window` is no longer a pure delete — it reads what it drops and
writes to a second table, inside `acquire()`'s hot path under `self._lock`. The cost is one
`RETURNING` clause plus at most one ledger read/write per affected cell per prune, against a
table deliberately kept small; acceptable next to the per-cell ledger reads `acquire()`
already does, but it is no longer free.

**A subtlety worth stating.** `note_request_sent` confirms the *oldest* unconfirmed row for
a backend, not the specific one its caller reserved. Reservations are therefore fungible
within a cell — the refund's *count* is exact, but no individual row maps to an individual
call. Nothing here needs that mapping; anything later that does must not assume it.

## Alternatives considered

**Move the RPD increment out of `acquire()` and into `note_request_sent`, fully mirroring
RPM.** The cleanest-sounding version, and wrong for the reason `_try_reserve_rpm` is a
single statement: between grant and send, concurrent callers would read a stale count and
all be admitted, overshooting the daily cap under exactly the fan-out this pipeline runs.
The reservation has to be visible immediately; only its *correction* can be deferred.

**Refund every request the provider didn't count, including 429s.** The larger share of the
drift, and it breaks termination — see "Why source 1 is deliberately left over-counting".

**Bound the per-minute retry loop with an explicit attempt cap, then refund freely.** Would
make the previous option safe. Rejected: it invents a tuning constant to replace a bound
that already exists and works, on the hottest correctness path in the governor.

**Reconcile against the provider's usage API instead of inferring locally.** Authoritative
by construction. Rejected as free-tier-hostile — it spends real requests on bookkeeping, and
the local evidence (`confirmed`) is already sufficient and free.

## Revisit when

- The refund log line starts appearing in volume. Phantoms should be a trickle; a stream
  means tasks are dying between grant and send somewhere that deserves its own fix, and the
  refund is masking it.
- `note_request_sent` stops being the first statement in `_invoke_with_backoff`. The
  "unconfirmed after five minutes means never sent" inference depends on that ordering.
- Something needs a reservation to map to a specific call (see "A subtlety worth stating").
- The deliberate 429 over-count starts costing meaningful headroom under sustained
  throttling — at which point the fix is a real bound on the per-minute retry loop, not a
  refund bolted onto this one.
