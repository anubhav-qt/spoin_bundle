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

---

# Hand-back (session 8, 2026-08-31) — **GO**

**Recommendation: GO.** Nothing structural blocks CockroachDB — no dialect wall,
no vector problem, no migration problem. The residue is a short list of well-scoped
fixes, mapped to tasks 0017–0019 below. Storage headroom (the whole reason for
ADR-0048) is intact. Proceed to 0017–0021.

## Harness (committed regardless of outcome)

- **`crdb` service** in [docker-compose.yml](../../docker-compose.yml), `profiles:
  ["crdb"]` (opt-in: `docker compose --profile crdb up -d crdb`; plain
  `docker compose up` is unchanged). Image `cockroachdb/cockroach:latest-v26.2`
  → **v26.2.6**. That is the version CockroachDB Basic serves today: v26.2 is the
  current *Regular* release (GA 2026-04-27) and Basic does not run *Innovation*
  releases (v26.3). Own volume `crdb-data`, never shared with `db`. DB Console
  :8080, SQL :26257.
- **`cockroachdb` optional extra** in [apps/api/pyproject.toml](../../apps/api/pyproject.toml)
  pinning `sqlalchemy-cockroachdb>=2.0.4,<2.1`. Not in the default install.
- The spike ran the suite via
  `docker compose --profile test run --rm --no-deps -T -e SPOIN_DATABASE_URL=... -e SPOIN_TEST_DATABASE_URL=... test`
  with both env vars pointed at a throwaway `..._test` database on the `crdb`
  node, `pip install`-ing the dialect on top of the image.

## Go/no-go, stated

**GO.** Reasoning: the only production-behaviour regression found (SKIP LOCKED,
below) leaves the job row `pending` and is recovered by the next worker pass, and
task 0019 already exists to build the retry/claim boundary it needs. Everything
else is either a one-line SQL fix (feed COALESCE), a latent app bug the port
surfaced (notes ordering), or test-infrastructure cost (DDL speed).

## Classified failure list (this is the scope of 0017–0019)

### dialect / driver — 1 finding, non-blocking

- **`sqlalchemy-cockroachdb` 2.0.4 hard-pins `SQLAlchemy<2.1,>=2.0.47`.** We floor
  `sqlalchemy>=2.0.36` with no ceiling; adopting the dialect adds a `<2.1` cap and
  raises the floor. Harmless today (2.1 unreleased) but it is a constraint where
  there was none, on a smaller, less-maintained package under every query. Driver
  stays asyncpg (the dialect bundles none). `cockroachdb+asyncpg://` connects and
  runs the full query set. Alembic auto-detects `CockroachDBImpl` and switches to
  non-transactional DDL on its own.

### DDL — no blockers; one performance finding

- **No blockers.** `Base.metadata.create_all` builds all 39 tables (enum types,
  arrays, `VECTOR`, partial indexes) clean. The **full 23-migration Alembic chain
  applies base → head (`07b6c1a3cb76`)**, produces 39 tables matching the live
  Postgres DB exactly, is idempotent on re-run, and `downgrade -1` works. (Task
  0018's doc still says "19 migrations" / "the first one will fail" — both stale;
  see below.)
- **`CREATE EXTENSION IF NOT EXISTS vector` is a no-op that SUCCEEDS on v26.2**
  (so does `CREATE EXTENSION postgis` — it is a generic compatibility shim). The
  ADR-0048 table row "`CREATE EXTENSION vector` — **Not supported**" and this
  task's own note "`...vector` … will fail — expect it" are **stale for
  v26.2**. Migration `f49f90af49c0:27` does not need a dialect guard to survive
  CockroachDB, though 0018 may still want one for clarity.
- **`VECTOR(384)` is native.** `create_all` emits it; `card.content_embedding`
  reports `data_type = 'vector'`. `<=>` (cosine), `<->` (L2), `<#>` (neg inner
  product) all work and order correctly. **`pgvector.sqlalchemy.Vector` can stay
  unchanged** — `domain/models/card.py` and `topic.py` are untouched. (The
  *extension* does not exist; the *type* is built in.)
- **`DISTINCT ON`, `ON CONFLICT DO UPDATE/DO NOTHING` (incl. on a non-PK UNIQUE
  index, with `excluded.*` and self-reference), partial/filtered UNIQUE indexes
  with `IN (...)` predicates, `STRING[]`/`BOOL[]`/`UUID[]` array columns,
  `CREATE TYPE ... AS ENUM`, the raw `date_trunc`/`dense_rank() OVER`/int×interval
  streak query in `profile/service.py`** — all pass.
- **Performance:** `create_all` ~8.8s, `drop_all` ~8.9s on CockroachDB (~40×
  Postgres). `conftest.py`'s `session` fixture rebuilds the schema **per test**,
  so the full suite runs >1h on CockroachDB vs ~25s on Postgres. Every DDL logs
  `NOTICE: waiting for job(s) to complete` (async schema-change jobs). This is
  test-infrastructure, not production — but ADR-0048's "the suite runs against
  CockroachDB after cutover" commitment needs the fixture reworked to
  session-scoped schema + per-test cleanup first (a session-scoped build +
  `DELETE`-per-test variant ran the suite in ~6.5min and matched Postgres results
  501/501, so the pattern is sound). Fold into 0017 or raise a new task.

### SQL — 1 finding

- **`feed/service.py` coverage-need `COALESCE` — breaks the entire feed read
  path.** Both `_eligible_cards` (~L471) and `_candidates` (~L645) build
  `func.coalesce(1.0 - cast(UserSubtopicProgress.seen_count, Float)
  / func.nullif(UserSubtopicProgress.total_count, 0), 1.0)`. SQLAlchemy renders
  `nullif(...)` as `CAST(... AS NUMERIC)`, so the division is `<float> / <decimal>`
  and CockroachDB rejects the COALESCE:
  `incompatible COALESCE expressions: unsupported binary operator: <float> /
  <decimal> (returning <float>)`. Postgres coerces silently. **17 of the 27
  suite failures (all of `test_feed_service`, all of `test_session_shares`) trace
  to this one expression.** Fix: cast the division (or the `nullif` result) to
  `Float` so both COALESCE arms are FLOAT; the two sites are identical, so extract
  a helper (0017's "change it in one place").

### semantics — 3 findings (the dangerous bucket)

1. **`FOR UPDATE SKIP LOCKED` skips freshly-committed, unlocked rows —
   timing-dependent.** Reproduced with the real `GenerationJob` model and the
   worker's exact claim query, **zero contention**: connection A commits a job,
   connection B immediately runs
   `SELECT ... WHERE status='pending' ORDER BY priority DESC, created_at
   LIMIT n FOR UPDATE SKIP LOCKED` — and *sometimes* gets the row, *sometimes*
   gets **0**. SKIP LOCKED treats an unresolved write intent (from the just-
   committed txn, not yet cleaned up) as "locked" and skips past it. Under
   `SERIALIZABLE`. This is the "skips rows it shouldn't" upstream behaviour this
   task flagged, and the flaky-test signature CLAUDE.md's note describes.
   - **Production impact on `worker/__main__.py:172`:** a worker pass can silently
     skip a `pending` job if the claim lands right after another txn committed
     one. Recoverable — the row stays `pending`, the next cron pass claims it —
     but it is a real "generation looks slow for no reason" regression.
   - Caused the ~9 `test_worker` + `test_repair_lane` suite failures (flaky).
   - **Also the over-locking variant** (from the isolated probes): `SKIP LOCKED`
     + `LIMIT n` with the filter column *not* covered by an index locks **every
     scanned row** (measured: 500 locks for `LIMIT 5` on 1000 rows), so a
     concurrent second claimer finds everything locked and gets nothing. An index
     on the filter column drops it to exactly `n`. `generation_job` already has
     `ix_generation_job_status_priority (status, priority)` (the `created_at`
     tiebreak is uncovered → small residual band); `quota_request`
     (`quota.py:1177`, filters `confirmed IS false`, unindexed) does not.
   - **Fix (decided with the owner this session): drop `SKIP LOCKED`, use plain
     `FOR UPDATE`.** One line. The reasoning: the claim transaction is *short* —
     `SELECT ... FOR UPDATE`, set `status='running'`, `COMMIT` — it ends in
     milliseconds, and generation runs in *separate* transactions after it
     (`worker/__main__.py`'s `session_scope()` block closes before `_run_job`
     is called). So with plain `FOR UPDATE`, a second overlapping pass blocks
     for those few milliseconds, then reads the rows as `status='running'` and
     its `WHERE status='pending'` returns nothing new. No double-claim (the
     property `SKIP LOCKED` was protecting), and no skipped-valid-row failure
     mode — plain `FOR UPDATE` *waits* for the write intent to resolve and then
     locks the row, which is exactly the behaviour we want. The `LIMIT`
     over-locking is a non-issue here precisely because the lock is held for
     milliseconds, not for the length of a generation run.
   - The `quota_request` claim (`quota.py:1177`) is the same short-transaction
     shape; give it the same treatment (plain `FOR UPDATE`, or add the
     `confirmed` column to `ix_quota_request_backend_sent_at`).
   - → **task 0019** for the mechanical change + the contention test. This is
     *not* bigger than a retry decorator after all — the retry boundary in 0019
     is for the *request* write paths (engagement upserts under real user
     load), not the worker claim.
2. **`ORDER BY` tie-break differs — latent app bug the port surfaced.**
   `notes/service.py:upsert` does `on_conflict_do_update(set_={"body": body})` and
   never sets `updated_at`; SQLAlchemy's `onupdate=func.now()` does **not** fire
   for `pg_insert().on_conflict_do_update()`. So "editing a note" never bumps its
   timestamp, and `list_for_user`'s `ORDER BY updated_at DESC` is sorting on tied
   values. Postgres and CockroachDB break the tie oppositely, so only CockroachDB
   fails `test_list_for_user_orders_newest_edit_first` — but the feature is
   broken on Postgres too. Fix: `set_={"body": body, "updated_at": func.now()}`.
   → task 0017, semantics bucket.
3. **FK check inside a single flush — observed, low risk.** Adding a parent and a
   child object and flushing them together (no intervening `flush()` on the
   parent) raises `ForeignKeyViolationError` on CockroachDB — the child's FK
   check does not see the not-yet-flushed parent. Real code and the fixtures
   flush parents first everywhere checked, so nothing is currently broken; note
   it for 0017 so nobody adds a batched parent+child insert later.

## Notes for the follow-up tasks

- **0017:** the SQL bucket has exactly one item (feed COALESCE). The semantics
  bucket has items 2 and 3 above, plus coordinating item 1 with 0019. The DDL
  performance / `conftest.py` rework is either 0017 or a new task — call it.
  Isolation level: **keep `SERIALIZABLE`** (CockroachDB default) and build the
  retry boundary, rather than dropping to `READ COMMITTED` — decided with the
  owner this session.
- **0018:** its "19 migrations" / "the first one will fail" framing is stale —
  there are **23** migrations and the chain **already applies clean base → head**
  on v26.2, extension line included. 0018 shrinks to: (a) decide whether to add a
  `op.get_bind().dialect.name` guard to `f49f90af49c0`'s `CREATE EXTENSION` line
  for clarity even though it is a harmless no-op; (b) verify the `seed` service's
  bind-mounted `alembic upgrade head` on a blank CockroachDB in the compose stack
  (the spike ran it in the `test` container with `alembic/` mounted); (c) confirm
  the async-DDL "waiting for job(s)" behaviour does not bite multi-statement
  migrations under load.
- **0019:** the worker job-claim fix is now *specified*, not open — drop
  `SKIP LOCKED` for plain `FOR UPDATE` on both `worker/__main__.py:172` and
  `quota.py:1177` (reasoning in semantics item 1 above). The `40001` retry
  boundary in `core/db.py` is still 0019's main body, but it's for the request
  write paths (`engagement`, `ensure_unlock_latched`), not the worker. Two
  concurrent claimers against the real CockroachDB node is still the test.

## Teardown

The `crdb` container + `crdb-data` volume are disposable:
`docker compose --profile crdb down -v` then `docker volume rm spoin_crdb-data`.
The throwaway `spoin_*_test` / `spoin_mech*` databases live only there. The
harness (compose service + pyproject extra) stays committed so this is not
rebuilt.
