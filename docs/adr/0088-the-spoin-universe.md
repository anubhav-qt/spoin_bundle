# ADR-0088: `the_spoin_universe` is a separate database with its own alembic environment; retrieval is cross-topic by default

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** project owner, implementing session
- **Amended by:** [ADR-0091](0091-corpus-category-hierarchy.md) — `document` gains
  `category`, `sub_category` and `scope`. The schema table below predates them.

## Context

[ADR-0087](0087-frog-is-a-sibling-package.md) established `frog` as the retrieval
package. It needs somewhere to keep the source-of-truth corpus that
[task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md) is built around.

The corpus is not application data. It is authored material — curated, revised, and
re-delivered repeatedly by an externally-owned track (Antigravity, supervised by the
owner). Its lifecycle, its backup requirements and its blast radius are all different
from `spoin_db_2`'s. Mixing authored reference material into the database that holds
users, cards and engagement events means every corpus revision is a migration against
production.

## Decision

**The corpus lives in `the_spoin_universe`, a separate database in the same Postgres
instance, with its own alembic environment owned by `frog`. Retrieval is cross-topic
by default.**

### ⚠️ The volume prohibition now protects three databases

`the_spoin_universe` shares the `db-data` volume with `spoin_db_2` and
`spoin_db_test`. CLAUDE.md's standing prohibition on `docker compose down -v`,
`make clean` and `docker volume rm` is unchanged and now costs more when violated.
Creating a database is non-destructive and does not relax anything.

### The alembic environment lives in `apps/frog/`, not `apps/api/`

`apps/api/alembic.ini` points at `SPOIN_DATABASE_URL`. frog gets its own
`apps/frog/alembic.ini` and `apps/frog/alembic/`, whose `env.py` reads
**`SPOIN_UNIVERSE_DATABASE_URL` and nothing else**.

This is the point of the choice, and it is a structural guarantee rather than a
convention: a universe migration cannot land on `spoin_db_2` because the environment
that runs it never reads the variable that names `spoin_db_2`. Two alembic
environments sharing a directory tree is precisely how a migration ends up on the
wrong database, which is a failure this project has paid for four times in a
neighbouring form.

Cost: a second compose service to run universe migrations, and `make migrate` /
`make migration` grow a universe counterpart.

### Schema

Two tables. Every column below is a decision, not a placeholder.

**`document`** — one authored source file.

| Column | Notes |
|---|---|
| `id` | UUID primary key |
| `source` | NOT NULL. URL or origin. Where the material came from. |
| `title` | NOT NULL. |
| `kind` | NOT NULL, Postgres enum: `spoin_canon` or `topic_source`. |
| `source_path` | NOT NULL, UNIQUE. Path within the delivered corpus; the document's identity. |
| `content_hash` | NOT NULL. sha256 of the raw file. Drives idempotent re-ingestion. |
| `source_date` | Nullable. When the *source material* is from — distinct from `ingested_at`. |
| `ingested_at` | NOT NULL. When we read it. |

**`chunk`** — a retrievable span of one document.

| Column | Notes |
|---|---|
| `id` | UUID primary key |
| `document_id` | FK to `document`, `ondelete=CASCADE` |
| `ordinal` | NOT NULL. Position within the document; makes a chunk citable as "part 3 of". |
| `text` | NOT NULL. |
| `embedding` | `Vector(384)` — the same space as `card.content_embedding` (ADR-0087). |
| `topic_tags` | `ARRAY(Text)`, GIN-indexed. |

#### Why `kind` is a real enum

Retrieval treats the two kinds differently and will keep doing so:
**Spoin canon** — how the product itself works, how a hook lands, the ASCII box rule,
[dual titles](0022-dual-titles.md), [archetypes](0017-card-archetypes.md) — is
relevant to nearly every generation call regardless of subject. **Topic
source-of-truth** is relevant by subject. A free-text column would let a front-matter
typo create a silent third kind that nothing ever retrieves. Adding a third kind later
being a migration is correct: it is a real decision.

#### Why topic tags are slugs, not foreign keys

`the_spoin_universe` is a separate database, so a chunk **cannot** hold a foreign key
to `spoin_db_2`'s `topic` table. Tagging crosses that boundary by value.

Tags are produced by the same `normalize_topic_text` that `spoin` applies before
embedding a topic string: one normalizer, so tags and canonical topic names cannot drift
into two vocabularies. **That requirement is what moved the function.** ADR-0087 kept it
in `spoin`; the ingester that produces these tags lives in frog, which cannot import
`spoin`, so [ADR-0093](0093-normalize-topic-text-moves-into-frog.md) moved it into
`frog.embeddings` and had `spoin` import it from there. They sit on `chunk` rather than `document` so a broad document can have
differently-tagged sections. GIN-indexed because they are a filter, even though the
filter is not applied by default.

#### Why idempotency is a content hash

The corpus will be re-delivered many times as it is supervised and revised.
Re-ingestion reads a file, hashes it, and skips the document if `content_hash`
matches; if it differs, that document's chunks are replaced in one transaction.

The alternative — a version field in front matter — is human-maintained, will be
forgotten at least once, and its failure mode is stale chunks silently surviving a
revision. A hash cannot be forgotten.

### Retrieval is cross-topic by default

A PostgreSQL card may legitimately ground itself in distributed-systems material.
`topic_tags` filtering is **available and not applied by default**.

The risk is real: retrieval can drag a card off its subtopic. The mitigation already
exists in the gate's topic-conformance check. But
[task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md) is explicit that this
must be **inspected in Phase 3 by looking at actual retrieval scores on cross-topic
hits**, not assumed away.

## Consequences

**Easier.** Corpus revisions never touch production data. The universe database can be
dropped and rebuilt from the delivered corpus at any time — it is derived, not
authoritative — which makes ingestion experiments cheap in a way nothing else in this
project is. A card can cite what grounded it, which is the "we can back with grounding
why our material is high quality" claim made storable.

**Harder.** Two databases means two connection URLs, two alembic chains, and two
backup concerns. `the_spoin_universe` is rebuildable from the delivered corpus, so the
hourly Neon backup does not need to cover it — but that is now a fact someone has to
remember rather than infer. No cross-database joins: anything wanting topic metadata
alongside a chunk does two queries and joins in Python. Topic tags can drift from
canonical topic names if `normalize_topic_text` changes, the same coupling task 0001
already flags.

**Committed to.** Same Postgres instance, therefore same volume, therefore three
databases behind one prohibition.

## Alternatives considered

**Corpus tables inside `spoin_db_2`.** No new database, no second alembic environment,
joins work. Rejected: every corpus revision becomes a migration against production, and
the corpus is re-delivered *many times*. It also puts derived, rebuildable data in the
one database that must never be rebuilt.

**A second alembic environment inside `apps/api/`.** Keeps migrations under one roof.
Rejected on the wrong-database argument above — the safety of the chosen option is that
the universe environment structurally cannot read `SPOIN_DATABASE_URL`.

**frog manages its own schema with `create_all` or plain SQL.** Simplest today.
Rejected: no migration history for a store that will evolve as the corpus is revised,
and no way to reason about what shape a given ingestion run wrote.

**Topic tags on `document` only.** Fewer rows to keep consistent. Rejected: loses the
ability to tag one section of a broad document differently, which is exactly what a
dense authoritative source looks like.

**An explicit version field for idempotency.** Rejected on the forgotten-bump argument.

## Revisit when

- Phase 3's retrieval-score inspection shows cross-topic hits pulling cards off
  subtopic more often than the gate catches. The fix is a default `topic_tags` filter,
  and it amends this ADR.
- A third content kind appears. That is a migration, and worth a moment's thought about
  whether `kind` is still the right axis.
- The corpus grows past what a single-instance pgvector index serves at generation
  latency. That is a scaling decision, not this one.
