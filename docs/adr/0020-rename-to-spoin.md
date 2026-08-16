# ADR-0020: Rename the product from Slocho to Spoin

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav, Mayank

## Context

"Slocho" was a working name. It was never validated against a domain, a trademark search,
or anyone outside the two of us, and it has no meaning that helps a first-time visitor
guess what the product does.

The cost of renaming is not flat over time — it rises sharply and permanently at three
points we have not yet crossed:

1. **Users.** Every rename after real accounts exist is a comms exercise, not a
   find-and-replace.
2. **Indexed presence.** A domain with backlinks, an app-store listing, and search
   history are not renameable at all; they are abandoned and rebuilt.
3. **Data.** The Postgres database name, the Alembic migration history, and the Python
   package path (`apps/api/src/slocho/`) are cheap to change while the only deployments
   are local `docker compose` stacks with seeded fixtures, and expensive once a
   production database exists that cannot simply be dropped and re-seeded.

We are currently before all three. That makes this a now-or-never decision rather than a
someday one — deferring it is equivalent to deciding to keep "Slocho" forever.

## Decision

The product is **Spoin**. The rename is executed as one mechanical sweep, now, before any
production deployment.

Scope of the sweep (execution tracked in [task 0007](../tasks/0007-rename-to-spoin.md)):

| Surface | Change |
|---|---|
| Python package | `apps/api/src/slocho/` → `apps/api/src/spoin/`, and every import |
| Packaging | `pyproject.toml` name, `Dockerfile` paths, `alembic.ini` |
| Database | database name in `.env.example`, `docker-compose.yml`, `alembic/env.py` |
| Web | app metadata, `<title>`, package name, visible copy |
| Docs | `README.md`, `CLAUDE.md`, `docs/**`, mockups in `docs/design/mockups/` |
| Repo | directory and remote name |

Two things are deliberately **not** in scope:

- **Migration history is not rewritten.** The existing Alembic revisions keep whatever
  identifiers they already have. Rewriting migration files to change a name that only
  appears in a comment or a connection string is churn with a real chance of breaking a
  chain that currently works.
- **No compatibility shim.** No `slocho` alias package, no redirect. There is no
  external consumer to be compatible with, and a shim would leave both names alive
  indefinitely, which is the outcome the rename exists to prevent.

The rename lands as a single commit. A half-renamed tree is strictly worse than either
end state, because it makes "which name is current?" a question the next session has to
answer by reading code.

## Consequences

**Easier**
- The name is settled before it becomes load-bearing, so no future session spends time
  asking whether to rename.
- A single sweep means `grep -ri slocho` returning zero hits is a complete, checkable
  definition of done.

**Harder**
- Every open branch or uncommitted work in flight conflicts with the sweep, since it
  touches nearly every file in `apps/api`. Anything outstanding should be merged or
  parked before it runs.
- Local developer databases named `slocho` stop matching the new default and need to be
  dropped and re-seeded. Acceptable precisely because the data is fixtures.
- `git log -S` and `git blame` across the rename commit get noisier — the usual price of
  a mechanical sweep.
- Committing to the name means the domain and a trademark check are now blocking on
  *this* name specifically, not a shortlist.

## Alternatives considered

**Keep Slocho and revisit after launch.** Rejected — this is the alternative that
silently decides the question. Every week of delay adds surface (deployments, links,
data) and there is no future point at which renaming is *cheaper* than today.

**Rename user-facing surfaces only, leave the code package as `slocho`.** Rejected: it
permanently splits the product's identity from its code, which means every new session
has to learn that the package name is historical. That is exactly the kind of
undocumented trivia CLAUDE.md exists to eliminate.

**Ship a `slocho` compatibility alias.** Rejected — see "Decision". There is no consumer
to keep working, and the alias's only real effect would be letting a stale import survive
code review.

## Revisit when

A trademark or domain conflict on "Spoin" surfaces. That is the only signal that should
reopen this; ordinary second-guessing of the name should not, because the whole point of
deciding now is that the cost only rises.
