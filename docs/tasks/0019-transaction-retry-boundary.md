# Task 0019: A transaction retry boundary for CockroachDB's `40001` errors

**Owner:** unassigned — **blocked on [task 0016](0016-cockroachdb-spike.md) returning go**

## The problem

CockroachDB under `SERIALIZABLE` isolation returns `40001` ("restart transaction") when
a transaction cannot be serialized against a concurrent one, and **expects the client
to retry**. CockroachDB retries internally where it can; `40001` is what reaches the
client specifically when it *cannot* resolve the conflict on its own.

Postgres, at our contention level, never made us think about this. So no code in
`apps/api` handles it. [ADR-0048](../adr/0048-cockroachdb-over-neon.md) names this as
the real cost of the migration: every write path inherits a new failure mode that has
no handler.

## Why it matters

Untreated, a `40001` surfaces as a 500 from an endpoint that would have succeeded on a
retry — an intermittent, contention-dependent, load-correlated error that is miserable
to reproduce and easy to misattribute. The endpoints most exposed are the ones with
concurrent writes to the same rows: `engagement/service.py`'s upserts into
`UserCardState` and the progress aggregates, `topics/service.py`'s
`ensure_unlock_latched` read-then-write latch, and the worker's job claim.

CLAUDE.md's rule that **a failed outcome and a rejected outcome are never the same
number** applies directly here. A retried-and-succeeded transaction, a
retried-to-exhaustion transaction, and a genuine business-rule rejection are three
different facts. Folding retries into a generic error count would make a contention
spike look like an application bug, which is the same class of mistake the pass-2
verification counter made.

## What to do

1. **Settle the isolation level jointly with [task 0017](0017-sql-portability-fixes.md)
   step 4.** `READ COMMITTED` sharply reduces how often `40001` reaches the client and
   is what `worker/__main__.py`'s existing comment already assumes; `SERIALIZABLE` is
   the CockroachDB default and gives stronger guarantees. This task's size depends
   heavily on the answer, so answer it first. Whichever wins gets an ADR-worthy
   paragraph explaining why — put it in ADR-0048's record or a new ADR if the reasoning
   is substantial.
2. **Put the retry in one place: `core/db.py`.** `session_scope()` already owns the
   commit/rollback boundary for workers and scripts, and `get_session()` owns it for
   requests. A retry decorator scattered across services would be both duplicated and
   incomplete. One boundary, so there is one place to read to know what the policy is.
3. **Retry only what is safe to retry.** A retry re-executes the transaction body, so
   the body must be idempotent. This is fine for pure database work and *not* fine for
   anything that has already spent LLM quota — `topics/service.py:request_topic` calls
   `validate_topic_names` and `match_and_create_topics` inside its transaction, and
   blindly retrying that would bill the quota ADR-0028 protects a second time. Identify
   every such path and either exclude it or restructure it so the retryable part is the
   database-only tail.
4. **Bound and instrument it.** A fixed retry ceiling with backoff, and log lines that
   distinguish *retried and succeeded* from *retried to exhaustion* — per the CLAUDE.md
   rule above, these are separate counts and the log must say which happened and why,
   not just how many.
5. **Test it against the real database with real contention.** Two concurrent sessions
   writing the same row, asserting the retry boundary absorbs it. Per CLAUDE.md, mock
   the generator and not the database: the database's concurrency behaviour is the
   entire subject here, so a mocked session proves nothing.
6. **Check whether `sqlalchemy-cockroachdb` already provides this.** The dialect
   documents retry support; if it handles the loop correctly at the SQLAlchemy layer,
   the right answer may be to configure it rather than write one. Verify what it
   actually does before building — and either way, step 3's quota-safety constraint
   still applies, because a library retry has no idea an LLM call is in the body.

## What to hand back

- The retry boundary, in `core/db.py`, with its policy documented in the module
  docstring — this is a "why", so it belongs there per CLAUDE.md's comment discipline.
- The list of transactions deliberately **excluded** from retry, and why each one is
  unsafe. This list is the valuable half of the deliverable.
- A contention test that fails if the boundary is removed.

## Open questions / notes for whoever picks this up

- **Our workload should have low contention.** Spoin is corpus-read-heavy with modest
  per-user writes; ADR-0011's event log is append-only with an idempotency key. If
  `40001` turns out to be *frequent* rather than rare, something is wrong with the
  access pattern and the retry loop would be hiding it — ADR-0048's "Revisit when"
  names this explicitly. Report the observed rate, don't just make the errors go away.
- **`ensure_unlock_latched` is the read-then-write pattern most likely to contend**
  (`topics/service.py`), since it reads a coverage snapshot and conditionally writes
  the latch. It is also the one where a lost update is user-visible as revoked
  progress. Worth examining directly rather than waiting for it to show up.
- **`pool_pre_ping` and pool sizing in `core/db.py` were tuned for Neon's connection
  cap** — the comment there says so. CockroachDB Basic has its own connection limits
  and its own RU cost for connection churn. Re-check that comment's premise while you
  are in this file; if it no longer holds, fix the comment in the same session.

## Timebox

Medium. Small if `READ COMMITTED` wins and the dialect already handles the loop;
larger if `SERIALIZABLE` is kept and step 3's quota-safety audit turns up several
transactions that need restructuring.
