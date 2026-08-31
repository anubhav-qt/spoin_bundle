# Task 0017: Fix the Postgres-only SQL the spike found

**Owner:** unassigned — **blocked on [task 0016](0016-cockroachdb-spike.md) returning go**

## The problem

The codebase was written against Postgres and says so out loud —
`topics/service.py:174` justifies `DISTINCT ON` with "Postgres-only, but this codebase
is Postgres-only by design (pgvector)". [ADR-0048](../adr/0048-cockroachdb-over-neon.md)
changes that premise. Every place that reasoning was applied needs re-checking against
what CockroachDB actually does.

Research says most of it survives — `DISTINCT ON`, `ON CONFLICT`, enums, arrays,
`JSONB`, and `VECTOR(384)`/`<=>` are all supported. This task exists for the residue,
and the residue is defined by task 0016's classified failure list, not by this doc.

## Why it matters

These are the failures that *do not announce themselves*. A dialect error is loud and
gets fixed in five minutes. A `SKIP LOCKED` that silently skips an unlocked row means
the worker quietly under-claims jobs and generation looks slow for no visible reason —
and per CLAUDE.md that reads as a content problem for a week before anyone traces it
back to the database.

## What to do

1. **Work the *SQL* and *semantics* buckets from task 0016's hand-back**, in that
   order. If a bucket is empty, close that half of this task explicitly rather than
   looking for work.
2. **Resolve `FOR UPDATE SKIP LOCKED` in `worker/__main__.py:125` first**, regardless
   of what the spike found, because it is the highest-consequence one. The comment
   there explains exactly what it is protecting: two overlapping worker passes
   double-claiming the same `GenerationJob` and billing the same generation twice
   against the quota ADR-0028 exists to protect. Whatever replacement lands must
   preserve that property, and must be tested with two concurrent claimers against the
   real database — this is precisely the case CLAUDE.md's "prefer the real Postgres
   `session` fixture over mocking" rule is about, since the database's locking
   behaviour *is* the thing under test.
3. **Where a construct must change, change it in one place.** If `DISTINCT ON` has to
   become a window function, `_latest_jobs_by_topic` is the only call site and its
   docstring's Postgres-only justification must be rewritten, not left contradicting
   the code (CLAUDE.md: a doc that is wrong costs more than no doc).
4. **Decide the isolation level deliberately and write down why.** CockroachDB
   defaults to `SERIALIZABLE`; it also offers `READ COMMITTED`, which sharply reduces
   `40001` retries and is what `worker/__main__.py`'s existing comment already assumes
   ("both read the same `pending` rows under READ COMMITTED"). This interacts with
   task 0019 — settle it jointly, and note that the documented `SKIP LOCKED`
   column-families caveat is specific to `SERIALIZABLE`.
5. **Add a guard for anything that must stay true.** If the conclusion is "no new
   Postgres-only construct may be introduced", wire it the way CLAUDE.md requires —
   a `ruff` `banned-api` entry or an AST check in `tests/test_architecture.py`, not a
   sentence in a doc. A rule stated only in prose is a wish.

## What to hand back

- The suite green against CockroachDB, with any test that had to change explained in
  its diff.
- A written decision on isolation level, with reasoning, handed to task 0019.
- A short list of anything found to be *unfixable* rather than merely different —
  that is ADR-0048 "Revisit when" material and must not be absorbed silently.

## Open questions / notes for whoever picks this up

- **Do not "fix" things that are merely unfamiliar.** CockroachDB supports far more of
  this than its reputation suggests. The temptation on a migration like this is to
  rewrite queries defensively; every such rewrite is a query no longer justified by a
  real constraint. Change what the spike proved broken.
- **`pgvector.sqlalchemy.Vector` probably stays.** Task 0016 answers this directly. If
  it works, leave `domain/models/card.py` and `domain/models/topic.py` alone — the
  import name says pgvector but what it emits is `VECTOR(n)` and `<=>`, which is
  CockroachDB-native. A comment noting that is worth adding, since the import will
  otherwise read as a bug to the next person.
- **`avatar_image` is a `LargeBinary` up to ~5 MB per row.** It is already `deferred`
  so the common path never loads it, which matters more on a per-RU-metered database
  than it did on Neon (ADR-0048's "second meter"). Verify the deferral still holds
  under the new dialect rather than assuming it survived — a lazy load that starts
  firing on `/auth/me` would be an RU leak, not just a latency regression.

## Timebox

Unknown by construction — scoped by task 0016's output. If that list is long enough
that this looks like more than a couple of sessions, that itself is a signal worth
taking back to ADR-0048 before continuing.

---

# Hand-back (session 9, 2026-08-31) — SQL + semantics buckets DONE

Worked the 0016 hand-back's SQL and semantics buckets. All shipped on branch
`feat/v1-finish-line`; `make check` green (Postgres); each touched file also
re-run against the `crdb` node.

1. **SQL — feed `COALESCE` (fixed).** Extracted `feed/service.py::_coverage_need_expr()`
   — the `1 - seen/total` coverage-need expression. The fix that works is
   casting **each division operand** to `Float`
   (`cast(seen, Float) / cast(nullif(total, 0), Float)`), not wrapping the
   whole `1.0 - …` in an outer cast: CockroachDB evaluates the division before
   the outer cast and rejects the `/` operator itself on `<float> / <decimal>`
   (SQLAlchemy renders the `nullif` divisor as `CAST(... AS NUMERIC)`). Verified
   the outer-cast-only version still failed on crdb before landing the
   operand-cast version. Called from both `_eligible_cards` (~L471) and
   `_all_active_cards` (~L645); the two byte-identical inline copies are gone.
   The `_eligible_cards` return annotation dropped `float | Decimal` → `float`
   and the now-unused `Decimal` import went with it; the stale "comes back as
   Decimal" comment was rewritten. `test_feed_service.py` +
   `test_session_shares.py` green on Postgres; the tests that run on crdb (the
   rest `skip` on the stock conftest's racy per-test schema build — see item 4)
   are green there too, 0 COALESCE failures (was ~17).
2. **Semantics — notes upsert `updated_at` (fixed).** `notes/service.py::upsert`'s
   `on_conflict_do_update` now sets `updated_at` explicitly — using
   **`func.statement_timestamp()`, not `func.now()`**. `now()` is the
   transaction timestamp and is constant across a transaction, so the spike's
   suggested `func.now()` still left `test_list_for_user_orders_newest_edit_first`
   tied (and it failed on crdb even with that change — three upserts in one test
   transaction). `statement_timestamp()` advances per statement on both dialects.
   Green on both.
3. **Semantics — FK-in-one-flush (note only, no code change).** Grepped every
   `session.add(` / `flush()` pair in `apps/api/src`: every parent→child insert
   already flushes the parent first (`_reuse_or_create_subtopic`,
   `_create_deep_dive_stubs`, `nodes.py`'s card→CardStats, `topic_match.py`,
   `repair.py`, the seed scripts). Left a comment at the canonical site —
   `generation/pipeline/nodes.py`'s card/`CardStats` flush — explaining why the
   two flushes must not be collapsed on CockroachDB.
4. **DDL perf — `conftest.py` rework: DEFERRED to task 0021.** Not landed this
   session. Rationale: the session-scoped-schema + `DELETE`-per-test fixture
   only pays off for *routine* CI against CockroachDB, and that is wired in the
   0021 cutover, not before. Landing a suite-wide test-infra rewrite now adds
   regression risk to a green suite that several in-flight tasks depend on, for
   zero benefit until 0021. The spike already proved the pattern (501/501 on
   both DBs, full suite ~6.5 min vs >1 h). 0021 should build it properly there:
   session-scoped build, `DELETE FROM` in FK-safe order (never `TRUNCATE` —
   non-transactional on crdb), fresh short-lived engine per test, clean
   `pytest.skip` with no DB, identical results on Postgres.

   **Note the cost of deferring, seen this session:** with the stock conftest,
   individual test files against crdb intermittently `skip` mid-run with
   `Database unavailable: relation "..." does not exist` — `Base.metadata.create_all`
   racing CockroachDB's async schema-change jobs. So crdb verification this
   session was per-file (some tests run, some skip) plus a standalone script
   for the worker-claim contention check (schema built once, outside pytest).
   The feed COALESCE fix is confirmed on crdb by the feed/session-share tests
   that *did* run; nothing crdb-side failed once the operand-cast landed.
5. **`DISTINCT ON` docstring (fixed).** `topics/service.py::_latest_jobs_by_topic`
   no longer claims `DISTINCT ON` is a Postgres-only compromise — the spike
   confirmed it runs on CockroachDB; the docstring now says so.

**Nothing found unfixable.** No ADR-0048 "Revisit when" material surfaced.

**Isolation level:** unchanged — `SERIALIZABLE` kept, per the 0016 decision.
Step 4 of this doc's original "what to do" (settle isolation) was already
resolved with the owner during the spike; recorded in 0019.

The worker/quota `SKIP LOCKED` → `FOR UPDATE` change (this doc's original step 2)
shipped as **task 0019 step 0** in the same session — see that doc.
