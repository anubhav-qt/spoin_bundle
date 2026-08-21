# Task 0021: Cut over to CockroachDB Basic, and instrument both meters

**Owner:** unassigned — **blocked on [task 0020](0020-corpus-migration-and-parity.md)**

## The problem

Tasks 0016–0020 prove the stack runs on CockroachDB locally and that the corpus
survives the move. This task points the deployed application at CockroachDB Basic in
the cloud, and adds the monitoring that makes
[ADR-0048](../adr/0048-cockroachdb-over-neon.md)'s "Revisit when" conditions
observable rather than aspirational.

## Why it matters

ADR-0048 traded **one meter for two**. Neon's free tier is storage-capped and that is
the whole story. CockroachDB Basic gives 10 GiB of storage *and* 50M Request Units per
month, and RUs are consumed by traffic — every read, write, and background job — not by
content. The storage ceiling is the one the ADR was chosen for; the RU ceiling is the
one it introduced, and nobody is watching it.

An unwatched meter is how a free tier turns into a surprise bill or a throttled
production database. ADR-0003's standing commitment is that free-tier limits get
verified, not assumed.

## What to do

1. **Re-verify the free-tier numbers against current provider documentation** before
   provisioning. ADR-0048's 10 GiB / 50M RU figures were verified 2026-08-22 and, per
   ADR-0003's committed-to section, have a shelf life. If they have moved, that is an
   ADR-0048 revisit, not a footnote in a commit message.
2. **Provision the CockroachDB Basic cluster** and run task 0018's migration chain
   against it, then task 0020's import and parity script. The parity report from the
   cloud database is the artifact that authorizes the cutover — not the local one.
3. **Update deployment configuration**: `SPOIN_DATABASE_URL` for the API and the
   worker's GitHub Actions cron (ADR-0003 §3). Verify the CI/cron path explicitly —
   the worker runs in a different environment from the API and is the easiest one to
   forget until generation silently stops.
4. **Instrument storage.** A recurring check of database size against the 10 GiB
   ceiling, surfaced somewhere a human sees. ADR-0048's revisit threshold is **8 GiB
   (~80%)** — the alarm should fire there, not at 10.
5. **Instrument Request Units.** ADR-0048's revisit threshold is **~50% of the monthly
   allowance**. Establish the baseline in the first full month: what a feed page
   actually costs in RUs against the real corpus, versus the ~50 RU estimate the ADR
   derived from documentation. If the measured number differs materially, correct the
   ADR — a projection that turned out wrong is worth fixing in place, since the next
   session will otherwise plan against it.
6. **Keep the Postgres path alive until the cutover is signed off.** The old Neon
   database and the local `db` service stay working, unmodified, as the rollback. Per
   CLAUDE.md, nothing about `spoin_db` gets torn down — no `docker compose down -v`, no
   dropped Neon branch — without separate explicit owner approval, and not until this
   task is closed.
7. **Update the docs that now describe the old world.**
   [docker-compose.yml](../../docker-compose.yml)'s header still says
   "db Postgres 17 + pgvector (Neon in production)";
   [apps/api/README.md](../../apps/api/README.md), the root README's stack table, and
   `core/db.py`'s pool-sizing comment about Neon's connection cap all encode the
   previous decision. CLAUDE.md is explicit that stale docs get fixed in the same
   session rather than noted and deferred.

## What to hand back

- The cloud parity report from step 2.
- Working storage and RU monitoring, with the first measured RU baseline written into
  ADR-0048 (or a correction to its estimate, if it was off).
- A rollback procedure, written down and *tested at least once* — pointing
  `SPOIN_DATABASE_URL` back and confirming the app comes up. An untested rollback is a
  belief, not a plan.
- Updated docs per step 7.
- An explicit sign-off note recording that the cutover is complete and Postgres is no
  longer authoritative — the trigger that finally allows decommissioning, in a separate
  conversation with the owner.

## Open questions / notes for whoever picks this up

- **Do not decommission anything in this task.** The deliverable is "CockroachDB is
  serving production and Postgres still could". Turning the old one off is a separate,
  owner-approved step after a period of running clean.
- **Cold starts and connection behaviour differ.** ADR-0003 §"Harder" already accounts
  for free services sleeping, and `core/db.py`'s pool settings were tuned for Neon's
  connection cap specifically. Check CockroachDB Basic's connection limits and idle
  behaviour, and re-tune with a comment explaining the new premise rather than leaving
  the Neon justification in place.
- **RU cost is query-shaped, not row-shaped.** Documentation notes that joins and index
  usage increase RU consumption. The feed read path (ADR-0010) is the highest-traffic
  query in the system and does real joins — it is the one to profile first, and the one
  whose cost most determines whether the 50M allowance holds.
- **`avatar_image`'s `deferred=True` matters more here than it did on Neon.** The
  comment in `domain/models/topic.py` explains it was deferred to avoid pulling up to
  5 MB on every `/auth/me`. On a per-KiB RU meter that is no longer just latency — it
  would be a direct, continuous cost. Task 0017 verifies the deferral survived the
  dialect change; confirm it again against the real cloud database.

## Timebox

Small-to-medium for the cutover itself; the monitoring in steps 4–5 is the part worth
doing properly, because it is what makes ADR-0048's revisit conditions real.
