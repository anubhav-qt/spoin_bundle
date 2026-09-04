# `frog` — retrieval

frog is Spoin's retrieval package: the embedder, the `the_spoin_universe` corpus
store, ingestion into it, and (from task 0038's Phase 3) retrieval over it.

**Read [ADR-0087](../../docs/adr/0087-frog-is-a-sibling-package.md) and
[ADR-0088](../../docs/adr/0088-the-spoin-universe.md) before changing anything here.**
Both encode rules whose violation is silent.

## What frog owns

| | |
|---|---|
| `src/frog/embeddings.py` | `Embedder`, `HashEmbedder`, `FastEmbedEmbedder` — pure classes, no settings |
| `src/frog/universe/` | `the_spoin_universe`: the `document`/`chunk` schema and its connection settings |
| `src/frog/ingest/` | The delivered corpus becomes `document`/`chunk` rows: contract validation, `##`-section chunking, idempotent upsert |
| `alembic/` | The corpus database's own migration chain |

## What frog does *not* own

**`get_embedder()` stays in `spoin.embeddings`.** Choosing between the classes reads
`spoin.core.config`, and frog cannot import `spoin`. Giving frog its own copy of
`embedding_dim` would mean two places configure the vector space, and a divergence
there produces vectors that are silently not comparable to `card.content_embedding`.

**`normalize_topic_text` used to stay in `spoin.embeddings` too. It doesn't
any more** ([ADR-0093](../../docs/adr/0093-normalize-topic-text-moves-into-frog.md)) —
it lives in `frog.embeddings` and `spoin` imports it. The ingester produces
`chunk.topic_tags`, `document.category` and `document.sub_category` with it, and the
ingester is on this side of the boundary. Unlike `get_embedder()` it reads no settings,
so moving it duplicates no configuration: there is one implementation, which is what
ADR-0088 required all along.

## The one rule

**frog must not import `spoin`.** The dependency runs `api -> frog`, one direction.
Enforced twice, per CLAUDE.md:

1. `ruff`'s `banned-api` entry in this package's `pyproject.toml`.
2. An AST check in `apps/api/tests/test_architecture.py`, which walks this source tree
   and fails in CI even if lint is bypassed locally.

## Working on it

frog is installed into the API image at `/app/frog`, and `make check` covers it —
`ruff` and `mypy --strict` here as well as in `apps/api`, and its test suite runs in
the same `make test` pass. There is no separate container to remember.

```bash
make check
```

## The corpus database

`the_spoin_universe` lives in the same Postgres instance as `spoin_db_2`,
`spoin_db_test` and `the_spoin_universe_test`, sharing the `db-data` volume.
**CLAUDE.md's prohibition on `docker compose down -v`, `make clean` and
`docker volume rm` is unchanged and now protects four databases.**

Its migrations are separate from the API's, deliberately:

```bash
make universe-migrate
```

```bash
make universe-migration m="describe the change"
```

`alembic/env.py` here reads `SPOIN_UNIVERSE_DATABASE_URL` **and nothing else**. Do not
add a fallback to `SPOIN_DATABASE_URL` — the absence of one is what makes it
structurally impossible for a corpus migration to land on production, and
`tests/test_universe_config.py` fails if anyone adds it back.

## Ingesting the corpus

The corpus is authored by a separate track against
[the ingestion contract](../../docs/handoff/antigravity-corpus-authoring.md). Ingestion
is **idempotent** — a document's identity is its `source_path` and change is a sha256 of
the file, so re-delivering an unchanged corpus writes nothing (ADR-0088). Assume it will
be re-delivered many times.

Validation first, because it needs neither a GPU nor a database:

```bash
make corpus-check
```

It reports **every** problem in **every** failing document, named by path and by field,
rather than dying on the first. That is deliberate: the corpus drifts in batches, and a
fail-fast validator turns one audit into a dozen sequential runs.

Then ingestion, which needs both:

```bash
make corpus-ingest
```

**This runs in the `frog` compose service — the only image in the project with torch and
a CUDA runtime.** ADR-0092 put bulk embedding on the owner's machine because only the app
backend deploys, so the api image every other service builds from stays free of ~3GB it
would never use. Run `make universe-migrate` first if the database does not exist yet.

Two things that are easy to get wrong here:

- **Ingestion embeds with `embed_passage`, never `embed_query`.** The corpus is what is
  being searched, not what is searching. Getting it backwards is a silent recall loss
  (ADR-0092).
- **`--embedder hash` produces a corpus that looks completely normal and is useless.** It
  exists for tests. Task 0039 is what happens when hash vectors sit somewhere real
  because nothing said so.
