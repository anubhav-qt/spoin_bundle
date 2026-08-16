# Task 0007: Execute the Slocho → Spoin rename

- **Owner:** unassigned
- **Timebox:** ~2 hours, including verification
- **Depends on:** nothing outstanding in flight — this touches nearly every file in
  `apps/api`, so merge or park open work first.
- **Background reading:** [ADR-0020](../adr/0020-rename-to-spoin.md), which is the decision
  and the scope. This doc is only the execution.

## The problem

The product is named Spoin. The tree still says Slocho in roughly 107 places across
package paths, imports, packaging metadata, database names, docs, and mockups.

The rename is cheap today only because there is no production database and no external
consumer. Both of those change once, permanently, in one direction — see ADR-0020's
"Context" for why this is now-or-never rather than someday.

## What to do

Land it as **one commit**. A half-renamed tree is worse than either end state, because it
turns "which name is current?" into a question the next session has to answer by reading
code.

1. **Python package.** `git mv apps/api/src/slocho apps/api/src/spoin`, then fix every
   `from slocho...` / `import slocho...`. Do not hand-edit — sweep, then let the test suite
   and a clean `docker compose up` find what the sweep missed.
2. **Packaging and tooling.** `apps/api/pyproject.toml` (name and package discovery),
   `apps/api/Dockerfile` (COPY paths, module path in the run command), `alembic.ini`, and
   `alembic/env.py`.
3. **Database name.** `.env.example`, `docker-compose.yml`, and any default in
   `core/config.py`. Local databases named `slocho` are dropped and re-seeded — the data
   is fixtures, which is exactly why this is safe now.
4. **Web app.** Package name, app metadata / `<title>`, and any visible copy.
5. **Docs.** `README.md`, `CLAUDE.md`, everything under `docs/`, and the committed
   mockups under `docs/design/mockups/` — a mockup that still says Slocho is a stale
   source of truth, which CLAUDE.md treats as worse than no doc.
6. **Repo.** Directory and git remote.

### Explicitly out of scope

- **Do not rewrite Alembic revision files** beyond the name in a connection string or
  comment. Rewriting a migration chain that currently works, to change a name that isn't
  load-bearing in it, is churn with real breakage risk.
- **Do not add a `slocho` compatibility shim.** There is no consumer to keep working, and
  its only real effect would be letting a stale import survive review.

## Hand back

- `grep -ri slocho` over the tree (excluding `.git` and `node_modules`) returns **zero**
  hits. That is the complete definition of done, and it is why the sweep is worth doing in
  one pass rather than incrementally.
- `docker compose up` brings up the full stack and serves seeded cards from a freshly
  created `spoin` database.
- The API test suite passes.

## Watch out for

- `__pycache__` directories carry the old package name and will show up in a naive grep.
  Clear them before verifying rather than chasing phantom hits.
- The rename commit makes `git log -S` and `git blame` noisier across that boundary. That
  is the accepted price of a mechanical sweep (ADR-0020, "Consequences") — don't try to
  avoid it by splitting the commit.
