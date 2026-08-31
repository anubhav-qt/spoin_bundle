# Task 0019: A transaction retry boundary for CockroachDB's `40001` errors

**Owner:** unassigned — unblocked, [task 0016](0016-cockroachdb-spike.md) returned GO.
**Step 0 (worker/quota claim) shipped in session 9 (2026-08-31);** the retry
boundary proper (steps 1–6) is still open.

## Step 0 — DONE (session 9)

`worker/__main__.py`'s `run_once()` claim and `quota.py`'s
`note_request_sent_with_session` reservation claim both dropped
`.with_for_update(skip_locked=True)` for plain `.with_for_update()`. The stale
`SKIP LOCKED` / `READ COMMITTED` comment block in `worker/__main__.py` was
rewritten to describe the short-claim-txn reasoning. New test
`test_worker.py::test_two_concurrent_passes_never_double_claim_a_job` runs two
`run_once()` passes concurrently against the real DB (batch size = half the
queue depth, `_run_job` stubbed to a bare status write) and asserts every job
is claimed by exactly one pass, none twice. Green on Postgres; `make check`
green (502). On CockroachDB it may `skip` (the stock conftest's per-test
`create_all` races crdb's async schema-change jobs — task 0021's fixture
rework), so the plain-`FOR UPDATE` claim was verified against crdb directly by
a standalone script: 5× two-concurrent-`run_once()`, clean 3/3 partition every
run, no double-claim.

> **Scope updates from the 0016 spike (2026-08-31):**
> - **Isolation level is decided: keep `SERIALIZABLE`** (CockroachDB default),
>   build the retry boundary. Owner call. Step 1 below is settled, not open.
> - **The worker job-claim is a separate, specified fix — not part of the retry
>   boundary.** The spike found `FOR UPDATE SKIP LOCKED` on CockroachDB can skip a
>   freshly-committed, unlocked row (write-intent resolution window). The claim
>   transaction is short (`SELECT … FOR UPDATE`, set `status='running'`, `COMMIT`;
>   generation runs in later transactions), so the fix is: **drop `SKIP LOCKED`,
>   use plain `FOR UPDATE`** on `worker/__main__.py:172` and `quota.py:1177`. A
>   second overlapping pass then blocks ~milliseconds and reads the rows as
>   `running` — no double-claim, no skipped row. Do this as step 0, with its own
>   two-concurrent-claimers test; it does not need the retry loop.
> - The retry boundary itself (the rest of this task) is for the **request**
>   write paths — `engagement/service.py` upserts, `ensure_unlock_latched` — under
>   real user contention.

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

0. **Fix the worker job-claim first (see the scope note above): plain `FOR UPDATE`,
   not `SKIP LOCKED`,** on `worker/__main__.py:172` and `quota.py:1177`. Update the
   `worker/__main__.py` comment that currently explains the `SKIP LOCKED` +
   `READ COMMITTED` reasoning — it no longer describes the code. Test with two
   concurrent `run_once()` claimers against the real CockroachDB node: neither
   double-claims, and every pending job is eventually claimed by exactly one.

1. ~~Settle the isolation level~~ **Settled: keep `SERIALIZABLE`** (CockroachDB
   default). Rationale for ADR-0048's record: `READ COMMITTED` would mask `40001`
   rather than remove the contention, and Spoin's write volume is low enough that
   a bounded retry at one boundary is cheaper than reasoning about the weaker
   guarantee everywhere. The `worker/__main__.py` comment that assumed
   `READ COMMITTED` is fixed in step 0.
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

Medium. `SERIALIZABLE` is kept (decided), so the size is driven by step 3's
quota-safety audit — how many transactions bundle an LLM call with database work
and need the retryable part split out. Step 0 (worker claim) is small and
independent; it can ship on its own first.
