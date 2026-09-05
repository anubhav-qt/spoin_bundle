# Task 0039: `SPOIN_EMBEDDER` never reaches the containers, so production vectors are hash vectors

> **Status: DONE**, 2026-09-05, by
> [ADR-0097](../adr/0097-one-embedder-one-vector-space.md) — which went further than
> this task proposed. Found the same day while surveying the RAG design space
> ([rag-design-space.md](../architecture/rag-design-space.md) §0).
>
> **What actually happened.** The owner's call was that a repair which re-embeds
> everything anyway should land on the model the corpus is authored for, not on the
> one this task assumed. So instead of `fastembed` at 384 dimensions, there is now ONE
> embedder — `Qwen/Qwen3-Embedding-0.6B` at 1024 — for cards, topics, questions,
> scenes, AskAI's gate and corpus retrieval alike. `get_corpus_embedder()` is gone.
>
> And instead of a resumable backfill, `spoin_db_2` was **dropped and rebuilt** from
> the migration chain (owner's explicit approval, off-machine Neon backup verified
> first). The discarded vectors were hash output, so nothing of value was in them, and
> the corpus is about to be regenerated against real retrieval regardless.
>
> The four numbered work items below all landed, item 2 included. Read them for why,
> not for what to do.

## What is wrong

`.env` sets `SPOIN_EMBEDDER=fastembed` and `SPOIN_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`.
`docker-compose.yml` **never passes `SPOIN_EMBEDDER` into the `api`, `worker` or `seed`
services**, and compose only injects variables it explicitly names — its own comments
say so, next to the `SPOIN_GENERATOR` and `SPOIN_GEMINI_API_KEYS` lines that *are*
spelled out for exactly this reason.

So `Settings.embedder` falls back to its default, `"hash"`. Verified in the container:

```
embedder setting : hash
model            : BAAI/bge-small-en-v1.5     <- set, and never read
actual class     : HashEmbedder
```

The image does install the `embeddings` extra, so `fastembed` is present and working.
Only the flag is missing.

## Blast radius

Measured on `spoin_db_2`, 2026-09-05:

| Column | Rows with a vector |
|---|---|
| `card.content_embedding` | 5,491 (all of them) |
| `topic.embedding` | 11 of 41 topics |

All hash vectors. `HashEmbedder`'s own docstring: *"Not semantically meaningful... Any
threshold measured against this is meaningless."*

Everything sitting on those vectors is affected: topic matching and the alias cache
(ADR-0025), the AskAI off-topic embedding gate (ADR-0077), the embedding-derived accent
colour (ADR-0075), near-duplicate card detection, and `content/ascii_library.py`'s
cosine search. None of them are *broken* in a way that raises — they simply degrade to
lexical-overlap behaviour, which is why this survived unnoticed.

It also blocks task 0038's Phase 3: retrieval over `the_spoin_universe` is meant to
share a vector space with `card.content_embedding` (ADR-0087), and half that space is
not currently a semantic space.

## Why the one-line fix is not the fix

Adding `SPOIN_EMBEDDER` to compose makes *new* vectors semantic while 5,491 existing
ones stay hash. A column holding both is **worse than a column holding either** —
comparisons across the two kinds are noise, and nothing raises. So the flag and the
backfill have to land together.

## The work

*All four are done — see the status note above for how items 1 and 3 changed shape.*

1. Pass `SPOIN_EMBEDDER` and `SPOIN_EMBEDDING_MODEL` into the `api`, `worker` and
   `seed` services in `docker-compose.yml`.
2. Add an `embedding_model` stamp to every embedded row, so a future model change can
   tell which vectors are comparable rather than guessing. This is the durable half of
   the fix — without it the same class of bug is invisible next time.
3. **Backfill:** re-embed all 5,491 cards and 11 topics. Bulk write to `spoin_db_2` —
   **requires the owner's explicit approval**, and should be a resumable script rather
   than one transaction.
4. Re-check anything with a tuned threshold against real vectors. Task 0001's
   calibration was measured against `HashEmbedder`, which its own docstring says is
   meaningless — so those thresholds are unvalidated, not merely stale.

   **This one is still open**, and it is the part of this task that outlives it: the
   thresholds are now *measurable* for the first time, and none of them have been
   measured. Task 0001 is where that lives.

## Related

- [rag-design-space.md](../architecture/rag-design-space.md) — §0, and why this gates
  everything in task 0038's Phase 3
- [task 0001](0001-topic-threshold-calibration.md) — thresholds measured against
  the stand-in
- [ADR-0087](../adr/0087-frog-is-a-sibling-package.md) — the shared 384-dim vector space
