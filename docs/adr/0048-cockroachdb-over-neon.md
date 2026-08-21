# ADR-0048: CockroachDB Basic over Neon, for corpus storage headroom

- **Status:** Accepted (amends 0003)
- **Date:** 2026-08-22
- **Deciders:** Anubhav

## Context

ADR-0003 picked Neon's free tier and stated the binding constraint plainly: **not
storage — LLM generation quota**. That was true when it was written, and it is still
true about *generation throughput*. It stopped being true about *storage* the moment
the target corpus size changed.

The product goal is now **1,000+ topics before paying anything**, with custom user
topics on top. That is a different number than ADR-0003 was reasoning about, and it
is what makes this a storage decision rather than a preference.

### What the corpus actually costs, measured

Measured against the live `spoin_db` on 2026-08-22 (read-only, `pg_database_size` and
row counts):

| | |
| --- | --- |
| Whole database | 46 MB |
| `card` / `question` tables | 21 MB / 13 MB |
| Topics with generated content | 7 (8 more exist as empty shells) |
| Cards / questions | 6,884 / 5,206 |
| **Per generated topic** | **~983 cards, ~744 questions, ~4.9 MB** |

Per-topic cost varies by roughly 3x — "Current AI Capabilities" is 476 cards, "Operating
Systems" is 1,739. So a topic costs **3–9 MB**, averaging ~5 MB.

Projected against the two ceilings:

| Corpus | Size | Neon free (500 MB) | CockroachDB Basic (10 GiB) |
| --- | --- | --- | --- |
| 7 topics (today) | 46 MB | 9% | 0.4% |
| 50 topics | ~260 MB | **52%** | 2.5% |
| ~100 topics | ~500 MB | **at the ceiling** | 5% |
| 1,000 topics (avg) | ~5 GB | 10x over | 50% |
| 1,000 topics (heavy) | ~9 GB | 18x over | **90%** |

**Neon's free tier runs out at roughly 100 topics** — a tenth of the stated goal, and
only twice the near-term 50-topic plan. This is not a distant problem being solved
early; it is reachable within the current expansion.

## Decision

**Move the corpus database from Neon to CockroachDB Basic**, whose free allowance is
10 GiB of storage per organization per month (part of a $15/month credit that also
covers 50M Request Units).

ADR-0003 §2's rule — *no accommodation may require a rewrite to undo* — is honored,
not waived. Scaling past 10 GiB on CockroachDB is still a billing toggle with an
unchanged connection string. What changes is *which* free tier we sit on before that
toggle, and the migration is paid for once, now, at 46 MB, rather than later at
5 GB under load.

**This decision is gated on a spike (task 0016) proving the stack runs on CockroachDB
at all.** If the dialect, vector, or migration story fails there, the fallback is
ADR-0003's original answer: pay for Neon. Do not force this through.

### What this decision is *not*

It is **not** an adoption of the event-streaming half of the proposal it came from.
Kafka is separately and explicitly rejected — see [ADR-0049](0049-no-message-broker-in-v1.md).
Storage was never a problem a message broker solves, and bundling the two would have
bought one real fix at the price of two new operational systems.

### The compatibility surface, verified rather than assumed

CockroachDB is Postgres-wire-compatible, not Postgres. What we actually depend on:

| Dependency | Status on CockroachDB | Where |
| --- | --- | --- |
| `VECTOR(384)`, `<=>` cosine distance | Supported natively; pgvector-compatible syntax | `dedup.py`, `topic_match.py` |
| `CREATE EXTENSION vector` | **Not supported** — the type is built in, no extension exists | `f49f90af49c0_initial_schema.py:27` |
| Vector *indexes* | L2 only; cosine is not index-accelerated | Moot — we have no vector index today |
| `DISTINCT ON` | Supported | `topics/service.py:184` |
| `INSERT ... ON CONFLICT` | Supported | 12 call sites across `engagement`, `feed`, `notes` |
| `FOR UPDATE SKIP LOCKED` | Supported, with a multiple-column-families caveat under `SERIALIZABLE` | `worker/__main__.py:125` |
| Enums, `JSONB`, arrays, `BYTEA` | Supported | throughout `domain/models/` |
| `asyncpg` async driver | Preliminary support via `sqlalchemy-cockroachdb` | `core/db.py` |
| Serialization failures (`40001`) | **New failure mode** — the app must retry; Postgres never required this | every write path |

The last row is the real cost of this ADR, and the reason task 0019 exists as its own
piece of work rather than a footnote.

**The vector-index row is the pleasant surprise.** CockroachDB's vector indexes only
accelerate L2, and our similarity work is cosine — which would matter a great deal if
we had a vector index. We don't: `find_corpus_duplicate` scans within a single
`subtopic_id` (~20 rows), and topic matching scans the `topic` table (1,000 rows at
goal size). Both stay linear scans on either database, so nothing regresses.

## Consequences

**Easier**

- 1,000+ topics fits in the free tier. The stated product goal becomes reachable
  without a bill, which is the entire point.
- Custom user topics stop being a storage risk we have to ration for storage reasons
  (ADR-0003's per-user cap stays, but for *quota* reasons, which is what it was for).
- The migration is done at 46 MB, which is small enough to export, import, and verify
  by hand in a session.

**Harder**

- **A second meter.** Neon's free tier is storage-capped. CockroachDB Basic meters
  storage *and* Request Units (50M/month free). At the documented rate — ~1 RU per
  64-byte row plus 1 RU per additional KiB — a ~3.2 KB card costs ~5 RU to read, so a
  10-card feed page is ~50 RU and the monthly allowance is on the order of a million
  feed pages. Not a near-term constraint, but it is a ceiling that *did not previously
  exist*, and it is driven by traffic rather than content. Task 0021 instruments it.
- **Transaction retries become the application's problem.** Under `SERIALIZABLE`,
  CockroachDB returns `40001` and expects a client-side retry. Postgres, at our
  contention level, never made us think about this. Every write path inherits a new
  failure mode (task 0019).
- **We take on a dialect.** `sqlalchemy-cockroachdb`'s asyncpg support is described by
  its own maintainers as preliminary. That is a smaller, less-maintained dependency
  sitting under every query in the project.
- **Local dev and production diverge unless we make them not.** Running Postgres
  locally and CockroachDB in production would reintroduce exactly the class of bug this
  ADR is trying to price honestly. Task 0016 moves the local target too.

**Committed to**

- Free-tier limits are re-verified against current provider docs before the cutover
  (ADR-0003's standing commitment; the 10 GiB and 50M RU figures here were verified
  2026-08-22 and have a shelf life).
- The test suite runs against CockroachDB, not Postgres, once the cutover lands. A
  compatibility rule that is only true in production is not a rule, it is a hope —
  same principle as CLAUDE.md's "enforced twice, never documented once".

## Alternatives considered

**Stay on Neon and pay when it fills (ADR-0003's original answer).** The honest
default, and still the fallback if task 0016 fails. Lost because the user's constraint
is explicit and not a preference: *no payment before 1,000+ topics*. Neon's free tier
cannot reach a tenth of that. Paying is a fine engineering answer to a question that
was not being asked.

**Stack several Neon free accounts and shard the corpus across them (~2 GB).**
Rejected on two counts. It is against the spirit and likely the letter of free-tier
terms, which puts the database itself at risk of suspension. And it violates ADR-0003
§2 harder than anything else on this list: cross-shard routing for `card` + `question` +
`card_stats` + engagement, plus similarity search across shards, is real application
code written specifically to be deleted later. It still tops out at 2 GB — under half
the goal — so it buys a rewrite and *still* doesn't get there.

**Self-host the database on the owner's laptop.** A strictly worse version of the
always-free-VM option ADR-0003 already rejected: it adds sleep/reboot/network
availability to the failure modes, requires tunnelling to be reachable, and exposes a
database from home hardware that two people would have to patch and secure themselves.

**Prune content to fit 500 MB** — shorter cards, fewer per subtopic, archiving cold
topics. Rejected because it trades the product's actual substance for infrastructure
convenience. Coverage-based progression (ADR-0009) is defined against card counts;
thinning the corpus to fit a database tier would quietly change what "mastery" means.

**Supabase / PlanetScale / other free tiers.** Supabase's free tier caps at 500 MB
(same wall as Neon) and pauses idle projects. PlanetScale dropped its free tier
entirely and is MySQL, which costs us `JSONB`, arrays, enums, and vector support in one
move. Neither reaches 1,000 topics.

## Revisit when

- **Task 0016 fails.** If the stack cannot run on CockroachDB — dialect, vector type,
  or Alembic — this ADR is void and ADR-0003's paid-Neon path is the answer. Record
  that outcome rather than quietly abandoning the migration.
- **RU consumption crosses ~50% of the monthly allowance.** That means traffic, not
  content, has become the binding meter, and the tradeoff this ADR made (trading a
  storage ceiling for a storage-plus-traffic ceiling) has stopped paying.
- **Storage passes 8 GiB (~80%).** At the heavy-topic end that is roughly 900 topics —
  close enough to the goal that the next decision is "start paying", as originally
  planned in ADR-0003 §2.
- **Serialization retries show up as user-visible errors** rather than being absorbed
  by task 0019's retry boundary. That would mean the contention profile is worse than
  a low-write, corpus-read workload should produce, and is worth understanding before
  papering over.
