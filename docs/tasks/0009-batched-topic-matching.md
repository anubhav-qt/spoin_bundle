# Task 0009: Implement batched LLM topic matching

**Status:** Done — executed 2026-08-17. `match_and_create_topics()` in
`generation/pipeline.py`; `ContentGenerator.match_topics` replaces
`judge_topic_match`/`TopicMatchVerdict`; `Settings.topic_merge_high/low` removed
(`topic_match_candidates` replaces them). Covered by
`tests/test_generation_pipeline.py` and `tests/test_langchain_impl.py`.

**Owner:** unassigned

**Background reading:** [ADR-0025](../adr/0025-batched-llm-topic-matching.md), then
[ADR-0004](../adr/0004-topic-canonicalization.md) for the model this replaces the matching
step of (the canonical-topic/alias/shared-entity schema is unchanged).

## The problem

`resolve_and_plan_topic` in `generation/pipeline.py` currently implements ADR-0004's
three-band matching (auto-merge above a high similarity threshold, an LLM judge in the mid
band, auto-new below a low threshold) via `judge_topic_match` — one LLM call per mid-band
topic, called from inside the per-topic graph branch.

ADR-0025 replaces this: no thresholds, every incoming topic gets an LLM opinion, but
batched into one call across however many topics the worker claims in a pass, run as a
pre-step before the per-topic pipeline branches even start.

## What to do

- Add a new function (outside `resolve_and_plan_topic`'s per-topic branch — this runs once
  per batch, before the graph's topic fan-out) that:
  1. Embeds every incoming topic request's name.
  2. Runs a pgvector cosine search for each, returning its top 5 nearest existing `Topic`
     rows with similarity scores.
  3. Makes **one** LLM call covering every topic in the batch, each with its top-5
     candidates + scores, and gets back a per-topic verdict: matched `topic_id` (if any)
     or none.
- Add a new `ContentGenerator` method for this batched verdict (replacing
  `judge_topic_match`, or added alongside it if `judge_topic_match` still has a use —
  check whether anything else calls it before deciding). Update `FakeContentGenerator`
  and `GeminiContentGenerator` accordingly.
- Wire this pre-step into `run_generation_pipeline` (or whatever calls it — see task
  0008/0010 for how the worker assembles a batch): topics that matched skip the pipeline
  entirely (just get aliased, per `_ensure_alias`); topics that didn't match proceed
  through curriculum → cards → questions as normal.
- Remove `resolve_and_plan_topic`'s three-branch band logic (the
  `topic_merge_high`/`topic_merge_low` threshold checks and the mid-band
  `judge_topic_match` call) — matching is now fully decided before this function runs.
  Check whether `Settings.topic_merge_high`/`topic_merge_low` become dead config.
- `topic_alias` caching behavior (never re-judge a decided pair) is unchanged — keep it.

## Hand back

The batched matching call implemented and tested (fake generator), `resolve_and_plan_topic`
simplified to assume matching already happened, and a note in `generation-pipeline.md`
describing the new flow.

## Timebox

Not started. Rough guess: half a day — this replaces one existing code path with another
of similar shape, the design work is already done in ADR-0025.
