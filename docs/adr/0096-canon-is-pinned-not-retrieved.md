# ADR-0096: Spoin canon is pinned into the prompt per call type, never retrieved

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** project owner, implementing session

> Amends [ADR-0088](0088-the-spoin-universe.md), which implied `spoin_canon` is
> retrieved by relevance like any other document. It is not. ADR-0088's `kind` enum is
> unchanged and is now load-bearing in a second way: it is the filter that keeps canon
> *out* of the retrieval budget.

## Context

`the_spoin_universe` holds two kinds of document (ADR-0088). `topic_source` is
subject matter, relevant to the handful of calls about that subject. `spoin_canon` —
what a card is, [dual titles](0022-dual-titles.md),
[archetypes](0017-card-archetypes.md), the ASCII box rule
([0021](0021-ascii-scene-library.md)), quiz-gated progression
([0009](0009-quiz-gated-progression.md)), CLAUDE.md's silliness-in-the-hook-layer rule
— is small, and relevant to **nearly every generation call regardless of subject**,
because a small model does not know our conventions.

[ADR-0089](0089-retrieval-grounded-generation.md) then made retrieval share one packed
token budget across everything a prompt carries. That is where the two kinds stop
being able to share a mechanism.

## Decision

**Canon is pinned into the system prompt as a fixed preamble, chosen per call type at
design time. Retrieval asks for `topic_source` only, and the whole retrieval budget
goes to subject matter.**

`generation/prompts/canon.py` holds ten preambles composed from shared fragments, and
`generation/grounding.py` passes `kinds=[TOPIC_SOURCE]` on every search.

### Why competing for a retrieval slot is wrong in both directions

A canon chunk that wins a slot displaces a fact the card needed. A canon chunk that
loses one leaves a call that needed the box rule without it. Neither failure
announces itself: the first looks like a thin corpus, the second like a model that
ignores instructions. Pinning removes both by removing the contest.

### Pinned per call type, not wholesale

The five canon documents are ~21k characters, roughly 5,300 prompt tokens, and
ADR-0089's table puts `ministral-8b` under target throughput above ~18k. Most of it is
irrelevant to any one call — the box rule means nothing to a prose card, curriculum
decomposition means nothing to a card writer. So relevance is still decided; it is
decided **at design time by a static map** rather than per call by an embedding. That
is still "pinned" in the sense that matters: canon never competes for a slot and never
fails to appear.

### Condensed, and guarded against drift

The preambles are condensed rather than quoted: the corpus states each rule with the
reasoning that earned it, which is what a human reading the corpus needs and about
three times what a model following the rule needs. A rule's *why* is kept only where
the why is what makes the rule followable.

That makes the preambles a **derived artifact of a corpus another track revises**, so
`CANON_SOURCE_HASHES` records the sha256 of each source document and
`test_canon_preambles.py` recomputes them. Revising a canon document fails that test by
name. The guard raises rather than passing when it cannot find the corpus — the `api`
image carries no `docs/`, so the `test` service mounts it read-only.

## Consequences

**Easier.** Every call gets the conventions it needs, deterministically. The retrieval
budget buys only facts. The 40-column box rule had five independent phrasings across
the prompts and now has one, so it can be corrected in one place.

**Harder.** A new call type needs someone to decide which fragments it gets, and
getting that wrong is silent — a call that edits existing artwork without the box rule
produces art that renders broken, and nothing raises. (This was gotten wrong twice
while writing the map: `fetch_ascii_scenes` adapts a library scene and `correct_cards`
rewrites art, and neither was given the box rule at first.) Prompt size grew: every
call is +200 to +836 tokens before a single retrieved passage.

**Committed to.** Keeping the condensation current with a corpus we do not own, with a
test as the tripwire rather than a convention.

## Alternatives considered

**Retrieve canon like anything else (ADR-0088 as written).** No new mechanism, and
canon stays in one place. Rejected on the displaces-or-misses argument above: it is a
correctness question, and similarity search answers it probabilistically.

**Pin all five documents on every call.** Simplest possible pinning, and no static map
to get wrong. Rejected on cost: ~5,300 tokens on every call, most of it irrelevant to
that call, against a budget where prompt size decides whether the target rate is
reachable at all (ADR-0089's table).

**Quote the canon documents verbatim into the preambles.** No drift possible, because
the preamble *is* the corpus text. Rejected on the same token argument, and on a second
one: corpus prose is written to persuade a human that a rule is right, and a model does
not need to be persuaded.

**Generate the preambles at build time from the corpus.** No hand-maintained
condensation and no drift guard needed. Rejected: condensation is an editorial
judgement about which reasoning changes behaviour, and a build step that made it
automatically would either quote everything or drop the wrong halves.

## Revisit when

- A call type is added and the map has to grow. That is the moment to check whether a
  static map is still the right shape, and specifically whether anything that EDITS
  artwork is missing the box rule.
- The drift guard fails often enough to be noise rather than signal — that means the
  canon documents are still being authored, and pinning is running ahead of them.
- Phase 4 measures real prompt sizes. If pinned canon is a large share of a prompt that
  is over budget, the per-call-type map gets finer rather than the pinning being undone.
