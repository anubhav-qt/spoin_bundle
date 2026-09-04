# `frog` — retrieval

frog is Spoin's retrieval package: the embedder, the `the_spoin_universe` corpus
store, and (from task 0038's Phase 3) retrieval over it.

**Read [ADR-0087](../../docs/adr/0087-frog-is-a-sibling-package.md) and
[ADR-0088](../../docs/adr/0088-the-spoin-universe.md) before changing anything here.**
Both encode rules whose violation is silent.

## What frog owns

| | |
|---|---|
| `src/frog/embeddings.py` | `Embedder`, `HashEmbedder`, `FastEmbedEmbedder` — pure classes, no settings |
| `src/frog/universe/` | `the_spoin_universe`: the `document`/`chunk` schema and its connection settings |
| `alembic/` | The corpus database's own migration chain |

## What frog does *not* own

**`get_embedder()` stays in `spoin.embeddings`.** Choosing between the classes reads
`spoin.core.config`, and frog cannot import `spoin`. Giving frog its own copy of
`embedding_dim` would mean two places configure the vector space, and a divergence
there produces vectors that are silently not comparable to `card.content_embedding`.

**`normalize_topic_text` stays in `spoin.embeddings`** too — it is
topic-canonicalization logic, and both task 0001's thresholds and this corpus's
`chunk.topic_tags` depend on there being exactly one of it.

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

`the_spoin_universe` lives in the same Postgres instance as `spoin_db_2` and
`spoin_db_test`, sharing the `db-data` volume. **CLAUDE.md's prohibition on
`docker compose down -v`, `make clean` and `docker volume rm` is unchanged and now
protects three databases.**

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
