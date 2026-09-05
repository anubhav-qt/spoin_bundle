# ADR-0097: One embedder, one vector space

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner

## Context

There were two embedders and two vector spaces.

`get_embedder()` returned a 384-dimensional model for `card.content_embedding`,
`topic.embedding` and `question.embedding`. `get_corpus_embedder()` returned
`Qwen/Qwen3-Embedding-0.6B` at 1024 dimensions for `the_spoin_universe`'s chunks
([ADR-0092](0092-qwen3-embedder-and-the-device-split.md)). The split was not an oversight — the two
columns genuinely held incomparable vectors, and one factory would have made every
retrieval a dimension error rather than a silent quality loss. Task 0039 was where
they were meant to converge.

Two things forced the question earlier than planned.

**Nothing was using a real embedder on the spoin side at all.**
[Task 0039](../tasks/0039-embedder-never-reached-the-containers.md) found that
`docker-compose.yml` never passed `SPOIN_EMBEDDER` into the `api`, `worker` or `seed`
services, and compose injects only the variables a file names. `.env` set `fastembed`;
`Settings.embedder` fell back to its `hash` default. Every vector in `spoin_db_2` —
5,491 cards, 1,665 questions, 11 topics — was `HashEmbedder` output, which its own
docstring calls semantically meaningless. Nothing raised, because nothing could: a
hash vector has the right dimension and the wrong meaning, and every consumer
degraded quietly to lexical-overlap behaviour.

**The corpus is written for one model.** `the_spoin_universe` is authored and chunked
deliberately, and ingested with Qwen3. A second model over the same material buys a
second set of thresholds, a second calibration, and a standing invitation to compare
across the two.

So the choice was not "which of two models" but "why two at all".

## Decision

**One embedder serves everything: `Qwen/Qwen3-Embedding-0.6B` at 1024 dimensions.**
Cards, topics, questions, ASCII scene matching, AskAI's off-topic gate and corpus
retrieval all use it.

Concretely:

- `get_corpus_embedder()` is deleted. `get_embedder()` is the factory, and its
  dimension is `frog.universe.models.EMBEDDING_DIM` rather than a setting — that
  constant is what the columns were created with, so a configurable that disagreed
  could only ever produce vectors the database refuses. `Settings.embedding_dim` and
  `Settings.corpus_embedder`/`corpus_embedding_model` are gone.
- `card.content_embedding`, `question.embedding` and `topic.embedding` widen from
  `vector(384)` to `vector(1024)` (migration `feded8588fd8`). Postgres cannot cast
  between them, so the migration nulls each column first. The discarded vectors were
  hash noise, and `spoin_db_2` was dropped and rebuilt from the migration chain with
  the owner's explicit approval rather than backfilled.
- Every embedded row carries an **`embedding_model` stamp**, fed by a new
  `Embedder.model_name` property. This is task 0039's durable half: without it a
  column can hold two incomparable kinds of vector and no query, log line or test can
  tell. The stamp is enforced by the database, not by the nine call sites that write a
  vector — `CHECK ((embedding IS NULL) = (embedding_model IS NULL))` on all three
  tables (`b9876ddc6238`), because nine correct call sites are discipline and a tenth
  is one merge away.
- `apps/api/Dockerfile` takes an `EMBEDDER_BACKEND` build arg — `gpu` (cu128 torch)
  for the worker, `cpu` for the api and the test suite, `none` for `seed` and
  `universe-seed`, which run alembic and never embed. `Qwen3Embedder` already passes
  `device=None`, so sentence-transformers picks CUDA where it exists and CPU where it
  does not; only the wheel differs, never the code path.
- `docker-compose.yml` passes `SPOIN_EMBEDDER` and `SPOIN_EMBEDDING_MODEL` explicitly
  to every service that embeds — the missing line that caused task 0039.
- The test suite runs the real model on CPU rather than a stand-in. Task 0039 is what
  happens when the thing under test is not the thing that runs.

`HashEmbedder` stays, dimension-correct and meaningless, for one purpose: a stack that
boots with no model weights on disk. It is not a fallback to select in anger.

## Consequences

**Easier.** One vector space, one dimension, one set of thresholds to calibrate. A
retrieval query is embedded by the model its chunks were, structurally rather than by
convention. Task 0039's "flag and backfill must land together" problem disappears —
there is no second kind of vector to land beside.

**Harder, and paid for deliberately.** The deployed api image now carries torch, on an
image [ADR-0094](0094-local-generation-lightweight-production.md) argues should stay
minimal. **Measured, not estimated: 539MB -> 2.46GB.** The CPU wheel is far heavier than
the ~800MB its download size suggests, and the worker's cu128 image is 12.3GB. That is the cost of AskAI's off-topic gate embedding on
the request path ([ADR-0077](0077-askai-deterministic-single-call-retrieval.md)) with
the same model as everything else, and it is why ADR-0092 chose 0.6B over the stronger
4B. `make test` also loads a real model, so the suite is slower than it was and CI
needs the weights cached; the `frog-model-cache` volume is mounted for exactly that.

**Unvalidated, and newly visible.** Every threshold in the system was calibrated
against hash vectors — [task 0001](../tasks/0001-topic-threshold-calibration.md) says
so explicitly, and the near-duplicate card threshold and the accent-hue distances have
the same problem. They are not stale, they are unmeasured. Real vectors make measuring
them possible for the first time; nothing here does that measurement.

**ADR-0094 is bent, not broken.** Heavy work still runs locally: only the worker gets
CUDA. What the production image gained is the ability to embed one short turn per
AskAI request on a CPU, which is what ADR-0092 sized the model for. ADR-0092's
deferred ONNX CPU path remains the way to drop torch from the deployed image; it is
now a size optimization rather than a prerequisite.

## Alternatives considered

**Keep two embedders, fix only the missing compose variable.** The one-line version of
task 0039. Rejected because it makes new vectors semantic while 5,491 stay hash, and a
column holding both is worse than a column holding either — comparisons across them
are noise and nothing raises. Fixing it properly meant a backfill anyway, and once a
backfill is on the table the dimension is free to change.

**Unify on the 384-dimensional model instead.** Cheaper: no migration, no torch in the
api image, no re-embed. Rejected because it points the wrong way — the corpus is the
asset, it is authored for Qwen3 and already ingested at 1024, and re-ingesting it to
match a weaker model chosen for its size would be optimizing the expensive thing for
the cheap one. BGE also needs a query prefix that this codebase never applied
(`FastEmbedEmbedder`'s docstring), so its recall was understated on top of everything
else.

**Package the ONNX CPU path now rather than torch.** `onnxruntime` is already in the
api image, so this would have kept it torch-free. Rejected as scope: it is a different
inference path from the one the corpus was embedded with, it needs its own export and
verification, and ADR-0092 deferred it until the backend actually deploys. Doing it
under time pressure to save 1.9GB on an image that is not yet deployed is the wrong
order. That number is the strongest argument for revisiting it once the backend ships.

**A build arg per service versus one image for all.** Installing torch unconditionally
is one line and no build matrix. Rejected because `api`, `worker`, `seed`, `test` and
`universe-seed` share the Dockerfile, and it would put ~3GB into the test and CI
images to serve one service — the exact argument `apps/frog/Dockerfile`'s header
makes. Measured after the fact, that argument was if anything understated: the CUDA
image is 12.3GB.

## Revisit when

- **The backend actually deploys.** Then torch's 1.9GB in the api image has a real
  bill attached, and ADR-0092's ONNX CPU path becomes worth building.
- **AskAI's gate latency is measured on a production-shaped CPU.** 0.6B was chosen to
  make this viable; if a turn's embedding is slow enough to be felt on the request
  path, the answer is the ONNX path or a smaller model on that path alone — and a
  second model on that path would reopen this ADR directly.
- **A thresholds pass runs against real vectors** (task 0001). If the numbers that
  come back say the model is wrong for topic canonicalization specifically, that is
  the evidence that would justify a second space — and it does not exist today.

## Related

- [ADR-0092](0092-qwen3-embedder-and-the-device-split.md) — chose the model, and one model across two
  devices. This ADR extends that to one model across two *spaces*.
- [ADR-0087](0087-frog-is-a-sibling-package.md) — says "shared 384-dim vector space";
  the sharing is now at 1024.
- [ADR-0094](0094-local-generation-lightweight-production.md) — the minimal production
  image, and what this costs it.
- [Task 0039](../tasks/0039-embedder-never-reached-the-containers.md) — the bug that
  forced the question, and where the stamp requirement comes from.
- [Task 0001](../tasks/0001-topic-threshold-calibration.md) — every threshold that is
  now measurable for the first time.
