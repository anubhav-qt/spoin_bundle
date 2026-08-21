# Task 0016: CockroachDB viability spike — does the stack run on it at all?

**Owner:** unassigned

**This task is a go/no-go gate.** [ADR-0048](../adr/0048-cockroachdb-over-neon.md) is
explicitly conditional on it. Tasks 0017–0021 do not start until this one says yes.

## The problem

ADR-0048 decided to move the corpus database from Neon to CockroachDB Basic for the
10 GiB free tier, because Neon's 500 MB ceiling runs out at ~100 topics against a
1,000-topic goal. The compatibility surface was researched from documentation, not
executed. Documentation says `sqlalchemy-cockroachdb`'s asyncpg support is
"preliminary"; that word is doing a lot of work in a project where every query in the
codebase sits on top of it.

## Why it matters

Everything downstream — schema migration, retry handling, the corpus export, the cloud
cutover — is wasted effort if the driver cannot run the existing query set. Finding
that out in task 0020, halfway through moving 46 MB of real production content, is the
expensive version of finding it out here.

The cheap version is: stand one up locally, point the existing test suite at it, read
the failures.

## What to do

1. **Add a `crdb` service to [docker-compose.yml](../../docker-compose.yml)** — a
   single-node insecure cluster (`cockroachdb/cockroach start-single-node
   --insecure`), its own volume, DB Console on 8080. Do **not** touch the existing `db`
   service or its volume: Postgres stays the working local database for the whole of
   this spike, and `spoin_db` is not to be migrated, mirrored, or pointed elsewhere
   (CLAUDE.md).
2. **Add `sqlalchemy-cockroachdb` and pin it** in
   [apps/api/pyproject.toml](../../apps/api/pyproject.toml). Note what it pins
   SQLAlchemy/asyncpg to — a dialect that constrains the SQLAlchemy version is itself a
   finding worth reporting.
3. **Create a `spoin_test` database on the CockroachDB node**, and run the existing
   suite against it: `SPOIN_TEST_DATABASE_URL=cockroachdb+asyncpg://.../spoin_test`.
   `conftest.py`'s `_reject_unsafe_test_database` guard already enforces the `_test`
   suffix — keep it, it applies here for the same reason.
4. **Record every failure, classified**, in the hand-back below. The classification is
   the actual deliverable, more than the pass rate:
   - *dialect/driver* — the connection or the DBAPI layer, not our SQL
   - *DDL* — table creation from `Base.metadata`, enums, arrays, `VECTOR(384)`
   - *SQL* — a query we wrote that CockroachDB rejects or answers differently
   - *semantics* — it ran, returned something, and the something was wrong
   The last category is the dangerous one and deserves the most attention.
5. **Probe the four constructs ADR-0048 flagged**, directly and in isolation, whether
   or not the suite covers them:
   - `VECTOR(384)` DDL, and `<=>` cosine distance ordering
     (`dedup.py:find_corpus_duplicate`)
   - `DISTINCT ON` (`topics/service.py:184`)
   - `FOR UPDATE SKIP LOCKED` with two concurrent claimers
     (`worker/__main__.py:125`) — the documented multiple-column-families caveat
     under `SERIALIZABLE` needs an actual answer for *our* tables, and there are
     open upstream reports of it skipping rows it shouldn't
   - `INSERT ... ON CONFLICT DO UPDATE` via `pg_insert`
     (`engagement/service.py`, 12 call sites)
6. **Write down whether `pgvector.sqlalchemy.Vector` can stay.** It emits
   `VECTOR(n)` DDL and the `<=>` operator, both of which CockroachDB supports — so
   the type may work unchanged even though the *extension* does not exist. If it
   works, say so explicitly; that keeps `domain/models/card.py` and `topic.py`
   untouched and is worth a lot.

## What to hand back

- A go/no-go recommendation, stated as such, with the reasoning.
- The classified failure list from step 4 — this becomes the scope of tasks 0017–0019.
  If a category is empty, say it is empty rather than omitting it.
- The `docker-compose.yml` and `pyproject.toml` changes, committed even on a "no":
  the next person to ask this question should not rebuild the harness.
- If **no-go**: a short note appended to ADR-0048 recording the outcome, per its own
  "Revisit when". A migration that quietly stops happening is worse than one that is
  written down as rejected — ADR-0003's paid-Neon path is then the answer.

## Open questions / notes for whoever picks this up

- **Which CockroachDB version.** Match the major version CockroachDB Basic actually
  serves today, not `:latest` — a local cluster ahead of the cloud one would validate
  features we cannot use. Check the Cloud docs before pulling the image.
- **Vector indexes are a red herring here.** CockroachDB only index-accelerates L2
  and our similarity is cosine, but we have *no vector index today* on either database
  (grep confirms: no `ivfflat`, no `hnsw`). Both stay linear scans. Don't spend spike
  time on index parity; do note it if the query planner behaves surprisingly.
- **`CREATE EXTENSION IF NOT EXISTS vector`** at
  `alembic/versions/f49f90af49c0_initial_schema.py:27` will fail — there is no such
  extension because the type is built in. Expect it; it is task 0018's problem, not a
  reason to stop here. Use `Base.metadata.create_all` (what `conftest.py` already
  does) to get past it for the spike.
- **`40001` serialization errors may show up as flaky tests**, not as clean failures.
  If tests pass on rerun, that is a finding, not noise — classify it under *semantics*
  and hand it to task 0019.

## Timebox

Small-to-medium — one focused session. It is deliberately scoped to *answer a
question*, not to make anything work. Resist fixing what you find; write it down and
let the follow-up tasks be scoped honestly against the real list.
