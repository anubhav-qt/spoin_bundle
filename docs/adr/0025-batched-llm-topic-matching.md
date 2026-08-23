# ADR-0025: Batched LLM topic matching, no similarity bands

- **Status:** Accepted
- **Date:** 2026-08-17
- **Deciders:** Anubhav
- **Amends:** [ADR-0004](0004-topic-canonicalization.md) (replaces the "Matching is
  banded, not a single threshold" section; the canonical-topic/alias/shared-entity model
  ADR-0004 establishes is unchanged)

## Context

ADR-0004 decided topic matching needed two stages: a cheap embedding pre-filter, then an
expensive LLM judge only for the ambiguous middle band, because paying for an LLM call on
every incoming topic looked wasteful against a hard free-tier quota (ADR-0003).

That design requires calibrated thresholds -- a labeled dataset, a chosen embedding model,
and two band boundaries placed where the merge/no-merge distributions separate (task
0001). Calibration is real, recurring work: it must be redone on every embedding model
change, and the three-way split (auto-merge / judge / auto-new) still risks a *false
auto-merge* landing above the high band with no LLM ever looking at it -- exactly the
failure mode ADR-0004 identifies as the expensive one ("a user asks for Java and receives
JavaScript").

Separately, [ADR-0026](0026-one-shot-generation-to-completion.md) establishes that
generation now happens in batches -- the worker claims several pending topic requests per
pass and processes them together, one call per topic in parallel (own session per topic,
for isolation). That batch is the unit already being assembled for other reasons, and it
changes the cost math: instead of "one LLM call per mid-band topic," we can afford "one
LLM call per **batch** of topics," because request count -- not tokens -- is the metered
resource, and a batch of N topics' candidates fits in one request same as one topic's does
(ADR-0005's reasoning, one level up).

## Decision

**Drop the threshold bands. Every incoming topic gets an LLM opinion, but batched: one
call per worker pass, not one call per topic.**

```
for the whole batch of incoming topic requests:
  1. embed each topic name (existing embedder, unchanged)
  2. pgvector cosine search -> top 5 nearest existing topics, per incoming topic
  3. ONE LLM call: every incoming topic + its top-5 candidates + their similarity
     scores, all in one prompt
  4. LLM returns, per incoming topic: match (which existing topic_id, if any) or none
```

No auto-merge path. No auto-new-without-a-look path. Every topic gets judged, but the
judging is amortized across the batch instead of paid per topic.

**Similarity scores are still computed and still passed to the LLM** -- they're useful
context (a 0.94 candidate is a different kind of case than a 0.71 one), but they no longer
gate anything themselves. The LLM is the sole decision-maker; the embedding step is purely
a recall filter (narrow ~thousands of topics down to 5 candidates) so the prompt stays
small.

**Threshold calibration (task 0001) is obsolete.** There is nothing left to calibrate --
no band boundary decides anything anymore. `docs/tasks/README.md` reflects this.

## Consequences

**Easier**

- No calibration step, no labeled dataset to build or re-run when the embedding model
  changes. One fewer piece of "tuned but is it actually tuned" surface area.
- No silent auto-merge failure mode -- every merge decision has an LLM behind it, so the
  "Java gets merged into JavaScript with nobody looking" case ADR-0004 worried about
  can't happen via this path anymore.
- Simpler code: `resolve_and_plan_topic`'s three-branch band logic (auto-merge / mid-band
  judge / new) collapses to one branch, decided upstream of the per-topic pipeline
  entirely.

**Harder**

- Every topic now costs one share of an LLM call, where before most topics (outside the
  mid band) cost nothing. In practice this is still cheap -- the call is batched across
  however many topics one worker pass claims, so it's amortized the same way a 10-card
  generation batch amortizes one request across 10 cards.
- The matching decision moves out of `resolve_and_plan_topic`'s per-topic branch and into
  a batch pre-step the worker (or whatever assembles a pass's topic list) runs before the
  pipeline even starts -- a structural change to where in the flow this decision lives.
- A batch with many genuinely-unrelated topics produces a bigger single prompt (N topics
  x 5 candidates x similarity scores). Not expected to be a problem at realistic batch
  sizes (`generation_batch_size`), but worth watching if that setting grows large.

**Committed to**

- The similarity search stays local/free (pgvector, existing embedder) -- only the
  final decision is an LLM call.
- The LLM call is genuinely one call for the whole batch, not one call looped per topic
  inside the batch -- that's the entire point of moving it here.
- `topic_alias` still caches every decision permanently, same as ADR-0004 -- a pair is
  never re-judged once decided.

## Alternatives considered

**Keep the three bands, just recalibrate periodically.** Rejected: still carries the
false-auto-merge risk ADR-0004 itself flags as the expensive failure mode, and still
requires ongoing calibration work for a marginal cost saving that a batched call
already captures more simply.

**One LLM call per topic (mid-band-style), always.** What ADR-0004 explicitly rejected on
cost grounds ("one LLM call per custom topic per user against a hard quota ceiling").
Still true in isolation; batching across the worker's pass is what makes "always ask"
affordable.

**No embedding pre-filter, LLM sees every existing topic.** Rejected: doesn't scale as
the topic count grows, and the pre-filter is nearly free (local, no quota) -- no reason to
drop it just because the LLM is now always in the loop.

## Revisit when

- The number of existing topics grows large enough that a top-5 pgvector search stops
  being a reliable recall filter (misses a true match outside the top 5) -- widen to
  top-10, or add an ANN index (ADR-0004's own revisit note already flags this).
- Batch sizes grow large enough that one matching call routinely produces a bad JSON call.
- Observed false-merge or false-split rate suggests the LLM needs better context in the
  prompt (e.g. subtopic titles, not just names/descriptions) -- same class of information
  ADR-0004's old mid-band judge already had access to (`judge_topic_match`'s
  `matched_subtopic_titles`) and this batched version should probably keep.

**Known gap (2026-08-23):** the "every merge decision has an LLM behind it" claim above has
one exception. `match_and_create_topics`'s slug-collision fallback (added in commit
`e6947a6` to fix an `IntegrityError` on insert) reuses an existing `Topic` on a raw slug
match with no LLM judgment and, unlike the LLM-match branch, never records an alias -- so
that merge decision isn't cached the way this ADR commits `topic_alias` decisions should be.
See [task 0022](../tasks/0022-slug-collision-skips-alias.md).
