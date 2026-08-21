# Task 0018: Make the Alembic migration chain apply cleanly on CockroachDB

**Owner:** unassigned — **blocked on [task 0016](0016-cockroachdb-spike.md) returning go**

## The problem

There are 19 migrations in
[apps/api/alembic/versions/](../../apps/api/alembic/versions/), and the first one opens
with:

```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

CockroachDB has no such extension — the `VECTOR` type is built into the database, so
there is nothing to create and the statement fails. That is the known blocker. The rest
of the chain is unverified: `alembic upgrade head` has never been run against
CockroachDB, and the tests reach the schema through `Base.metadata.create_all`
(`conftest.py`), which bypasses migrations entirely. So a green test suite proves the
*models* work and says nothing about whether the *migration chain* does.

## Why it matters

Migrations are how the production database gets its schema. Task 0020 imports 46 MB of
real production content into a database that has to have been migrated first, and
`docker compose`'s `seed` service runs `alembic upgrade head` on every local boot. A
chain that only works on Postgres means the CockroachDB cutover has no schema story at
all.

CockroachDB also handles DDL differently from Postgres — schema changes run
asynchronously as background jobs, and its transactional-DDL semantics are not
Postgres's. A migration chain that assumes "each `op.` completes before the next line
runs" may or may not hold.

## What to do

1. **Run `alembic upgrade head` against a blank CockroachDB database** and work the
   failures in order. Not `create_all` — the actual chain, from base, the way
   production will get its schema.
2. **Fix the extension statement without rewriting history.** ADR-0003's local
   Postgres is still the dev database until the cutover, so migration `f49f90af49c0`
   must keep working on both. Prefer a dialect check (`op.get_bind().dialect.name`)
   over deleting the line — an existing migration that no longer reproduces the schema
   it claims to is worse than a conditional.
3. **Verify the chain is idempotent and re-runnable**: base → head on a blank database,
   then `head` again as a no-op. If any step depends on an earlier DDL having fully
   applied, CockroachDB's async schema changes are where that assumption breaks.
4. **Confirm the resulting schema matches the models.** `alembic revision
   --autogenerate` against a freshly-migrated CockroachDB database should produce an
   empty migration. If it produces a diff, the chain and the models disagree on that
   database, and you need to know which one is wrong before task 0020 imports data
   into it.
5. **Update the `seed` service in [docker-compose.yml](../../docker-compose.yml)** so
   the migration path is exercised on every local boot against whichever database local
   dev is pointed at. The service comment there ("Migrations only -- no fixture
   loading") stays accurate and stays true.
6. **Check that `make migration` still generates usable migrations** under the new
   dialect. If autogenerate emits Postgres-flavoured DDL that CockroachDB rejects, every
   future schema change inherits this task's problem, and that is worth solving now
   rather than each time.

## What to hand back

- `alembic upgrade head` green from base on a blank CockroachDB database.
- An empty autogenerate diff against that database.
- Confirmation the chain still applies on Postgres — until the cutover completes, both
  must work, and after it the Postgres path is what makes a rollback possible.
- A note on whether `make migration` needs changing, and what.

## Open questions / notes for whoever picks this up

- **Do not squash the migration chain to make this easier.** It is tempting — one
  fresh initial migration against CockroachDB would sidestep 19 files of archaeology.
  It also destroys the ability to roll a production database forward from its current
  state, which is exactly what task 0020 and the cutover depend on. If squashing looks
  genuinely necessary, that is an ADR-sized decision, not a task-level one.
- **`alembic downgrade` is a CLAUDE.md-gated operation** against `spoin_db`. Doing this
  work on a *blank throwaway* CockroachDB database is fine and needs no approval;
  pointing any of it at `spoin_db` needs the owner's explicit go-ahead, every time.
- **Enums are the most likely quiet failure.** `domain/base.py`'s `pg_enum` helper is
  used for `Difficulty`, `CardStatus`, `TopicEdgeKind`, `SeenState`, `EngagementKind`
  and more. CockroachDB supports `CREATE TYPE ... AS ENUM`, but enum *alteration* in a
  later migration is where the dialects diverge most — check any migration that adds a
  value to an existing enum.

## Timebox

Small if the chain mostly applies, medium if the DDL-ordering assumptions bite. Task
0016's *DDL* failure bucket is the best predictor available before starting.
