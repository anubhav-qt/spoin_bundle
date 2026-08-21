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
