# Handoff: task 0038 Phase 2 — the ingester ("tadpole grows legs")

> Written 2026-09-05 at the end of the session that landed Phases 0–1 and ADR-0092.
> Paste the prompt at the bottom into a fresh session, or read this directly.

---

## What you're picking up

`apps/frog` exists, is type-checked, and has an empty schema waiting for content.
Antigravity has authored 31+ corpus documents. Nothing reads them yet. **Your job is
Phase 2: the ingester** — the machinery that turns those markdown files into
`document` and `chunk` rows in `the_spoin_universe`.

After you, Phase 3 is retrieval and the eval harness. Not your job; don't start it.

## Read in this order

| | |
|---|---|
| `CLAUDE.md` | the bootstrap, especially "The database" — there are three now |
| [`docs/tasks/0038-...`](../tasks/0038-frog-rag-and-hybrid-generation.md) | the plan. Phase 2 is yours |
| [`docs/handoff/antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md) | **the ingestion contract — you are building the other half of this** |
| [`docs/the_spoin_universe/procedure.md`](../the_spoin_universe/procedure.md) | how the corpus is authored, and what Phase B expects to query |
| ADRs [0087](../adr/0087-frog-is-a-sibling-package.md) [0088](../adr/0088-the-spoin-universe.md) [0089](../adr/0089-retrieval-grounded-generation.md) [0091](../adr/0091-corpus-category-hierarchy.md) [0092](../adr/0092-qwen3-embedder-and-the-device-split.md) | the decisions you are implementing |
| [`docs/architecture/rag-design-space.md`](../architecture/rag-design-space.md) | why any of this exists, and what comes after |

## Already true — don't redo it

- **`apps/frog/` is a real installed package**, sibling to `apps/api`, with its own
  `pyproject.toml`, ruff/mypy config, alembic chain and tests, all wired into
  `make check`. It must never import `spoin` — enforced by a ruff `banned-api` entry
  **and** an AST check in `apps/api/tests/test_architecture.py`.
- **Schema is done**: `document` (source, title, kind, category, sub_category, scope,
  source_path, content_hash, source_date, ingested_at) and `chunk` (document_id,
  ordinal, text, `Vector(1024)`, topic_tags). Three migrations, head
  `c3d4e5f6a7b8`.
- **`Embedder` is asymmetric** — `embed_query` / `embed_passage` (ADR-0092).
  Ingestion is the passage side. Getting this backwards is a silent recall loss.
- **`Qwen3Embedder` exists** (`Qwen/Qwen3-Embedding-0.6B`, 1024-d) behind the
  `embeddings-gpu` extra.
- **A `CHECK` enforces the hierarchy**: `topic_source` rows need `category` and
  `scope`; `spoin_canon` rows must not be forced to have them.
- `make check` is green: 529 api tests + 18 frog tests.

## Things that will waste your time if you don't know them

**`the_spoin_universe` does not exist yet.** The owner creates it —
`make universe-migrate`. Ask them to run it; don't create it yourself.

**The api image is built from the repo root, and every service has its own image.**
`docker compose build api` alone leaves `spoin-test` stale, which fails as
`ModuleNotFoundError: No module named 'frog'`. Build `api test seed worker` together.

**torch is not in the image.** `Qwen3Embedder` needs the `embeddings-gpu` extra, which
the Dockerfile does not install, and the container has no GPU. **Generation now runs
manually on the owner's home PC (RTX 5070); only the app backend deploys.** So how the
ingester gets a real embedder is an open question — see "Ask" below. Do not quietly
ingest with `HashEmbedder` and draw conclusions from it.

**Containers still run `HashEmbedder`** — `SPOIN_EMBEDDER` never reaches them
([task 0039](../tasks/0039-embedder-never-reached-the-containers.md)). All 5,491 card
vectors in `spoin_db_2` are hash output. Unfixed on purpose; the fix needs a backfill.

**Alembic constraint names need `op.f()`.** Without it the metadata naming convention
prefixes the name twice and autogenerate reports a phantom diff forever.

**ruff is pinned** to `>=0.16.6,<0.17` in both packages. An unpinned rebuild was a
formatting event once already.

**DB safety.** Three databases share the `db-data` volume. `docker compose down -v` /
`make clean` / `docker volume rm` remain prohibited — they now cost three databases.
`spoin_db_2` is archived at `.archives/spoin_db_2_2026-09-05.dump` (verified: 41
topics, 447 subtopics, 5,491 cards) and is slated for a wipe + full regeneration
**later**, when regeneration is actually ready. Not now.

## Two problems you will hit in the first hour

### 1. The normalizer is on the wrong side of the boundary

ADR-0088 says `chunk.topic_tags` are produced by `normalize_topic_text`, and ADR-0091
says `category`/`sub_category` are normalized the same way — *"so tags and canonical
topic names cannot drift into two vocabularies."*

**`normalize_topic_text` lives in `spoin.embeddings`, and frog cannot import `spoin`.**
The ingester lives in frog. This is a real contradiction introduced when ADR-0087 kept
the function in `spoin` while ADR-0088 gave it a second caller on the other side of the
boundary.

Recommended fix: **move `normalize_topic_text` into frog** and have `spoin` import it,
exactly as the `Embedder` classes were moved. ADR-0087 kept it in `spoin` because it is
"topic-canonicalization logic, and task 0001's thresholds depend on it" — but it is a
pure function with no settings dependency, which is what made `get_embedder()` different.
Duplicating it instead would recreate the exact drift the rule exists to prevent.
Whichever way you go, it amends ADR-0087 and the ADR must say so.

### 2. 18 of 31 corpus documents violate the contract

`title` is required by the contract and `NOT NULL` on `document`. It is **missing from
18 documents** — every `topic_source` file under `frontend-engineering/`,
`fullstack-engineering/`, and `mythology/`. The `backend-engineering/` batch has it.

The `spoin_canon` files correctly omit `category`/`sub_category`/`scope`, which
validates the CHECK's design — so the contract is mostly holding; this is one field
that drifted between authoring runs.

Do not silently derive a title from the H1 or the filename to make ingestion pass. Ask
(below). And note the corpus is being authored *while you work* — expect new commits
mid-session and re-check counts rather than trusting these numbers.

## The build

`frog/ingest/`, driven by a CLI entrypoint. Roughly:

1. **Walk** `docs/the_spoin_universe/corpus/`, skipping `README.md`.
2. **Parse** YAML front matter + body.
3. **Validate against the contract** — and fail loudly, per document, with the path and
   the field. A corpus this size will drift again; the ingester is where that is caught.
   Report every bad document rather than dying on the first.
4. **Hash** the raw file (sha256) → `content_hash`.
5. **Skip** if a `document` with this `source_path` has the same hash. Otherwise replace
   its chunks **in one transaction** (`ondelete=CASCADE` already does the deletion).
   Idempotency is the requirement: the corpus is re-delivered many times.
6. **Chunk on `##` headings.** Measured on the real corpus: median ~291 tokens, max
   ~583, only ~4% over 512. Section-level is right; don't invent a splitter.

   > ⚠️ **These numbers were wrong** and the Phase 2 session repeated them before
   > checking. Re-measured over 358 sections with `Qwen3-Embedding-0.6B`'s own
   > tokenizer: **median 339, max 1385, 17% over 512.** The conclusion held — no
   > splitter — but only after adding an enforced section size limit, because at 17%
   > the guideline was plainly not holding on its own. See task 0038's Phase 2 record.
7. **Embed** with `embed_passage`, in batches.
8. **Upsert** document + chunks, `ordinal` in document order.

Then: `make check` green, tests for the idempotency path specifically (re-ingest
unchanged → no new rows; re-ingest changed → chunks replaced, not duplicated), and a
short section in the task doc recording what Phase 2 actually landed.

Commit message theme: **"tadpole grows legs"**.

## Ask the owner — don't decide alone

- **How the ingester gets a real embedder**, given torch/GPU is not in the container and
  generation now runs on the home PC. Options include a GPU-enabled compose service, a
  host-side script outside Docker, or ingesting on the home PC only. This shapes the
  whole entrypoint; ask before building it.
- **The 18 missing titles** — does Antigravity fix them, or does the ingester derive
  them? Deriving is a contract change, not a convenience.
- **Contextual chunk headers** (rag-design-space §3.8) would be cheapest to add here,
  at ingestion. Worth raising; not obviously in Phase 2's scope.
- **The ASCII box rule** enforcement mechanism — still open from task 0038 Phase 6, five
  options tabled, needs its own ADR.
- **Anything that writes to, migrates, or repoints `spoin_db_2`.**

---

## The prompt

```
Read CLAUDE.md first, then docs/handoff/next-frog-phase-2-ingester.md.
That doc is your brief; task 0038 Phase 2 is the work — build the ingester
for the_spoin_universe. Everything the repo can't tell you is in it,
including two problems you'll hit in the first hour (the normalizer is on
the wrong side of frog's import boundary, and 18 corpus documents are
missing a NOT NULL field).

Read before writing code, in this order:
  docs/tasks/0038-frog-rag-and-hybrid-generation.md    the plan
  docs/handoff/antigravity-corpus-authoring.md         the ingestion contract
  docs/the_spoin_universe/procedure.md                 how the corpus is authored
  docs/adr/0087, 0088, 0089, 0091, 0092                the decisions you implement

Don't start Phase 3 (retrieval, eval harness). Don't create the corpus
database yourself — ask me to run `make universe-migrate`. Ask me the
questions listed under "Ask the owner" before implementing them.
```
