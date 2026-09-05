# Task 0042: every vector-similarity threshold was tuned against hash vectors

> **Status:** opened 2026-09-05, on the back of
> [ADR-0097](../adr/0097-one-embedder-one-vector-space.md). Not startable until
> `spoin_db_2` holds real content again — there is nothing to measure against an empty
> database.
>
> This task exists because the pointer that was supposed to hold this work does not.
> [Task 0039](0039-embedder-never-reached-the-containers.md) and ADR-0097 both sent it
> to [task 0001](0001-topic-threshold-calibration.md), which has been **obsolete since
> 2026-08-17** — ADR-0025 replaced the three-band topic thresholds it calibrates with a
> batched LLM call, so there is nothing there to pick up. The work is real; its home
> was not.

## What is wrong

Until 2026-09-05 every vector in `spoin_db_2` was `HashEmbedder` output (task 0039).
`HashEmbedder`'s own docstring: *"Not semantically meaningful... Any threshold measured
against this is meaningless."*

So every number in the system that compares two vectors was chosen by looking at
similarity scores that carried no meaning. They are not stale, and they are not
approximately right — they are **unmeasured**. A threshold tuned against token-hash
overlap has no particular relationship to the same threshold under Qwen3.

ADR-0097 made them measurable for the first time. Nothing has measured them.

## What needs recalibrating

| Where | Value | What it decides |
|---|---|---|
| `Settings.card_duplicate_threshold` | `0.9` | Whether a freshly drafted card is rejected as a near-duplicate of one already in the corpus (`find_corpus_duplicate`). Too low silently discards good cards; too high fills the feed with restatements. |
| `content/accent_color.py` hue distances | see ADR-0075 | Which accent hue a topic gets, and the minimum distance between two topics' hues. |
| ~~retrieval `min_score`~~ | **permanently unset** | Not part of this task. The owner settled it on 2026-09-05: grounding takes the top 2 with no floor, because the curated corpus covers a topic before that topic is live. See ADR-0089's amendment. |

The scores are worth knowing anyway, because they bound how much a threshold can
separate: Phase 3's pools put all 440 similarity scores in 0.236–0.836 with a median of
0.421 — a tight band. Whatever `card_duplicate_threshold` becomes, it is being asked to
cut a distribution narrower than the 0-to-1 range its current 0.9 implies.

## The work

1. Wait for real content. This needs a populated `spoin_db_2` and real Qwen3 vectors.
2. For `card_duplicate_threshold`: sample pairs across the range, hand-judge "is this
   the same card", and find where the judgement flips. The current 0.9 is a guess
   inherited from a meaningless measurement, not a starting point worth defending.
3. For the accent hues: check that the vocabulary distances still separate topics
   sensibly under a 1024-dim space — ADR-0075's list was built against 384-dim hash
   vectors, so both the hue assignments and the min-distance may be wrong.
4. Delete `SPOIN_TOPIC_MERGE_HIGH` / `SPOIN_TOPIC_MERGE_LOW` from `.env.example`. No
   setting reads them — they are the fossil of the system ADR-0025 removed, and they
   are why task 0001 looks live when it is not.

## Related

- [ADR-0097](../adr/0097-one-embedder-one-vector-space.md) — one embedder, and why
  these numbers are newly measurable
- [Task 0039](0039-embedder-never-reached-the-containers.md) — why they were
  meaningless
- [ADR-0075](../adr/0075-embedding-derived-topic-accent-color.md) — the hue vocabulary
