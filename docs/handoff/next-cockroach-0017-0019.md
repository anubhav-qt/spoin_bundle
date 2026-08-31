# Handoff: CockroachDB portability — tasks 0017 / 0019-step-0 (then 0018)

**Written:** 2026-08-31 (end of session 8). Paste the "Prompt" block into a fresh
session. Branch `feat/v1-finish-line`, pushed, HEAD `4e809e2`.

---

## Prompt

> Continue spoin v1 on branch `feat/v1-finish-line` (pushed, HEAD `4e809e2`).
> `git fetch` and check `origin/feat/v1-finish-line` before pushing — the remote
> has had outside pushes before.
>
> Read `CLAUDE.md`, then [`docs/tasks/0016-cockroachdb-spike.md`](../tasks/0016-cockroachdb-spike.md)'s
> **Hand-back** section (bottom of the file) — it is the source of truth for this
> work. [ADR-0048](../adr/0048-cockroachdb-over-neon.md) returned **GO**.
>
> This session: the two small, independent CockroachDB-portability fixes —
> **task 0017's SQL/semantics items** and **task 0019 step 0 (worker claim)**.
> Leave 0019's retry boundary and 0018 for later sessions unless there's time.
>
> ### Before you start: bring the spike harness back
>
> The `crdb` container + volume were torn down at the end of session 8 (they're
> disposable). To get a CockroachDB to test against:
>
>     docker compose --profile crdb up -d crdb
>
> It's `cockroachdb/cockroach:latest-v26.2` (v26.2.6, what Basic serves), profile-
> gated so plain `docker compose up` is unchanged. DB Console :8080, SQL :26257.
> Run the suite against it with **both** env vars pointed at a throwaway DB:
>
>     docker compose --profile test run --rm --no-deps -T \
>       -e SPOIN_DATABASE_URL="cockroachdb+asyncpg://root@crdb:26257/spoin_ci_test?ssl=disable" \
>       -e SPOIN_TEST_DATABASE_URL="cockroachdb+asyncpg://root@crdb:26257/spoin_ci_test?ssl=disable" \
>       --entrypoint sh test -c 'pip install --no-cache-dir "sqlalchemy-cockroachdb>=2.0.4,<2.1" >/dev/null 2>&1
>       python - <<PY
>     import asyncio
>     from sqlalchemy.ext.asyncio import create_async_engine
>     from sqlalchemy import text
>     async def m():
>         e=create_async_engine("cockroachdb+asyncpg://root@crdb:26257/defaultdb?ssl=disable",isolation_level="AUTOCOMMIT")
>         async with e.connect() as c:
>             await c.execute(text("DROP DATABASE IF EXISTS spoin_ci_test CASCADE"))
>             await c.execute(text("CREATE DATABASE spoin_ci_test"))
>         await e.dispose()
>     asyncio.run(m())
>     PY
>     pytest -q -p no:randomly --tb=short 2>&1'
>
> **The stock `conftest.py` rebuilds the schema per test (~18s on CockroachDB), so
> the full suite takes >1h.** For iteration, run single files / single tests. A
> known-good fast fixture (session-scoped schema built once, `DELETE`-per-test
> cleanup, one short-lived engine per test) ran the whole suite in ~6.5min on
> CockroachDB and matched Postgres 501/501 — the spike proved the pattern but did
> NOT commit it. If you want it, that's task 0017's "conftest rework" item (see
> below); write it properly (it needs to also work on Postgres and skip cleanly
> with no DB). Do NOT commit a half-baked fixture.
>
> ### Task 0019 step 0 — worker/quota claim: plain `FOR UPDATE`
>
> One-line changes, own contention test. See the scope note at the top of
> [`docs/tasks/0019-transaction-retry-boundary.md`](../tasks/0019-transaction-retry-boundary.md).
>
> 1. `worker/__main__.py:172` (`run_once`'s claim) — `.with_for_update(skip_locked=True)`
>    → `.with_for_update()`. Rewrite the long comment above it: it currently
>    explains the `SKIP LOCKED` + `READ COMMITTED` reasoning, which no longer
>    describes the code. New reasoning: the claim txn is short (lock → set
>    `status='running'` → commit; generation runs in later txns), so a second
>    overlapping pass blocks ~ms then reads the rows as `running` and its
>    `WHERE status='pending'` returns nothing new — no double-claim, and plain
>    `FOR UPDATE` waits for a write intent to resolve instead of skipping the row
>    (the CockroachDB `SKIP LOCKED` bug the spike found).
> 2. `quota.py:1177` (`note_request_sent_with_session`'s reservation claim) — same
>    change, same shape. (Or: add `confirmed` to `ix_quota_request_backend_sent_at`
>    so the `LIMIT 1` locks one row — but plain `FOR UPDATE` is simpler and
>    consistent with the worker.)
> 3. Test: `test_worker.py` already has `test_coalescing_lock_prevents_duplicate_pending_jobs_for_same_topic`
>    and the `run_once` tests. Add one that runs **two concurrent `run_once()`**
>    against the real DB (crdb) and asserts: no job is claimed twice, every
>    pending job is claimed by exactly one pass. Per CLAUDE.md, real `session`
>    fixture, mock only the generator.
> 4. This must still pass on Postgres — plain `FOR UPDATE` is standard there too.
>
> ### Task 0017 — the SQL/semantics residue
>
> Work the buckets in [0016's hand-back](../tasks/0016-cockroachdb-spike.md#classified-failure-list-this-is-the-scope-of-00170019):
>
> 1. **SQL — feed `COALESCE` (breaks the whole feed on CockroachDB).**
>    `feed/service.py` `_eligible_cards` (~L471) and `_candidates` (~L645) both
>    build `func.coalesce(1.0 - cast(UserSubtopicProgress.seen_count, Float)
>    / func.nullif(UserSubtopicProgress.total_count, 0), 1.0)`. SQLAlchemy renders
>    `nullif` as `CAST(... AS NUMERIC)` → the division is `float/decimal` →
>    CockroachDB rejects the COALESCE (`incompatible COALESCE expressions:
>    unsupported binary operator: <float> / <decimal>`). Fix: wrap the
>    division (or the whole `1.0 - …` expression) in `cast(..., Float)` so both
>    COALESCE arms are FLOAT. The two sites are byte-identical — extract a module
>    helper (`_coverage_need_expr()` or similar) and call it from both, per 0017's
>    "change it in one place". Verify on **both** Postgres and CockroachDB
>    (`test_feed_service.py` + `test_session_shares.py` are the coverage — all
>    green on PG today, ~17 fail on crdb before the fix).
> 2. **Semantics — notes upsert never bumps `updated_at`.**
>    `notes/service.py:upsert`'s `on_conflict_do_update(set_={"body": body})`
>    doesn't set `updated_at`, and SQLAlchemy's `onupdate=func.now()` does NOT
>    fire for `pg_insert().on_conflict_do_update()`. So "edit a note" never
>    changes its timestamp — `list_for_user`'s `ORDER BY updated_at DESC` sorts
>    tied values, and the tie breaks opposite ways on PG vs crdb (only crdb fails
>    the test, but the feature is broken on both). Fix:
>    `set_={"body": body, "updated_at": func.now()}`. `test_notes.py::test_list_for_user_orders_newest_edit_first`
>    is the check.
> 3. **Semantics — FK-in-one-flush (note only, likely no code change).** On
>    CockroachDB, adding a parent + child and flushing together (no `flush()` on
>    the parent first) raises `ForeignKeyViolationError`. All current code and
>    fixtures flush parents first, so nothing's broken — grep for `session.add(`
>    pairs without an intervening `flush`/`commit` to confirm, then leave a short
>    comment somewhere sensible (or a `test_architecture`-style note) so nobody
>    adds one later.
> 4. **DDL perf — `conftest.py` rework (call it: 0017 or its own task).**
>    Per-test `drop_all`/`create_all` is ~18s on CockroachDB. Decide whether to
>    land the session-scoped-schema + `DELETE`-per-test fixture now (so CI against
>    CockroachDB is viable, per ADR-0048's commitment) or defer it to the cutover
>    (task 0021). If you land it: it must build once, clean up with `DELETE FROM`
>    (NOT `TRUNCATE` — non-transactional on crdb, breaks cross-connection
>    visibility), use a fresh short-lived engine per test, still `pytest.skip`
>    with no DB, and still pass identically on Postgres. The spike verified this
>    exact shape = 501/501 on both.
> 5. `topics/service.py:_latest_jobs_by_topic`'s docstring says `DISTINCT ON` is
>    "Postgres-only … this codebase is Postgres-only by design (pgvector)". The
>    spike confirmed `DISTINCT ON` works on CockroachDB — update that docstring so
>    it doesn't contradict reality (CLAUDE.md: a wrong doc costs more than none).
>
> ### Process
>
> - Lint via the container: `docker compose exec -T api sh -c 'ruff check src tests && ruff format --check src tests && mypy src'`.
> - `make check` runs ruff + `mypy src` + pytest (against **Postgres** —
>   `spoin_db_test`). Keep it green per commit. Also run the crdb suite for the
>   files you touch.
> - Live DB is `spoin_db_2`; read-only SQL is fine, any write needs owner
>   approval every time. Don't start generation runs or touch
>   `docs/notes/topic-queue.md`.
> - Commit per logical change. When done, `docker compose --profile crdb down -v`
>   + `docker volume rm spoin_crdb-data` to clean up, and bring the normal stack
>   back (`docker compose up -d`).
> - After: update 0016's hand-back / 0017 / 0019 with what actually shipped, and
>   add a session-9 entry to `docs/handoff/v1-finish-line-plan.md`'s progress log.

---

## Session 8 recap (what's on the branch)

Commits since `5943318` (all pushed, HEAD `4e809e2`):

- **`46acf34`** `feat(generation): reject unquoted punctuation in mermaid edge
  labels` — `_mermaid_structural_issue` flags `|…|` flowchart labels with
  unquoted `()[]{}`; quoted labels pass; `CAM[(Camera2D State)]` cylinder nodes
  untouched. Prompt rule in `CARDS_DIAGRAM_SYSTEM`. 5 tests, `make check` green.
- **`52478c9`** `fix(content): quote mermaid edge labels on card 0afd7193` —
  owner-approved live `UPDATE` on `spoin_db_2`; the two edge labels wrapped in
  double quotes, verified. (Empty commit — DB change, recorded for history.)
- **`c643146`** — marked `docs/handoff/next-mermaid-label-guard.md` DONE.
- **`bc5c2b1`** `chore(spike): CockroachDB test harness` — `crdb` compose service
  (profile `crdb`), `cockroachdb` pyproject extra (`sqlalchemy-cockroachdb>=2.0.4,<2.1`).
- **`2ac5ac5`** — task 0016 spike → **GO**. Full hand-back in the task doc;
  ADR-0048 spike-outcome note + two stale table rows corrected; README updated;
  session-8 progress entry.
- **`4e809e2`** — worker/quota claim fix specified as plain `FOR UPDATE` (not a
  redesign); 0019 rescoped, isolation settled as `SERIALIZABLE`.

**Spike verdict:** GO. No structural blocker. Full 23-migration Alembic chain
applies clean base→head on v26.2 (39 tables, matches live Postgres). `VECTOR`/`<=>`
native — `pgvector.sqlalchemy.Vector` stays, models untouched. `CREATE EXTENSION
vector` is a harmless no-op on v26.2. Residue = the 0017/0019-step-0 items in the
prompt above. Full suite on CockroachDB: 474/501, every failure explained.

**Not done:** 0018 (Alembic — now mostly verification, see 0016 hand-back "Notes
for the follow-up tasks"), 0019's retry boundary proper, 0020/0021, B7.
