# ADR-0089: Generation is grounded in retrieved corpus context, packed against a token budget, and each card records the chunks that grounded it

- **Status:** Accepted, **partially superseded 2026-09-05**
- **Date:** 2026-09-04
- **Deciders:** project owner, implementing session
- **Amended by the owner, 2026-09-05:** the token budget is gone and grounding is a
  **fixed top 2** — the alternative this ADR rejected below. Grounding itself, and the
  `grounded_chunk_ids` provenance, are unchanged and still stand. Two things the ADR
  did not know moved the answer; both are recorded in the rejected alternative and in
  `Settings.grounding_chunks`. The title's "packed against a token budget" no longer
  describes the code.

## Context

Today the writer drafts from parametric knowledge and the gate checks it *after the
fact* ([ADR-0030](0030-two-pass-quality-gate.md)). There is no source-of-truth corpus
and no retrieval over one — verified: nothing in `generation/` or `content/` does
topic-level factual grounding. The truth guarantee for a product whose claim is
"quiz-gated mastery of true things" is entirely post-hoc.

That was tolerable while the drafter was `gemini-3.x-flash`. It stops being tolerable
under [ADR-0090](0090-hybrid-gemini-mistral-generation.md), which moves drafting onto
`ministral-3b/8b`. A 3B model's parametric recall is not a foundation.

[ADR-0087](0087-frog-is-a-sibling-package.md) built the retrieval package and
[ADR-0088](0088-the-spoin-universe.md) built the corpus store. This ADR says what
generation actually does with them.

## Decision

**Retrieval grounds generation upstream of the gate, context is packed against an
explicit token budget, and the chunk IDs that grounded a card are recorded on it.**

### Both drafters and thinkers retrieve

The verification pass grounds its factual check in **the same corpus the drafter
used**. This is the point of the design, not a nicety: a gate checking a grounded
draft against its own parametric memory reintroduces exactly the unreliability the
corpus exists to remove, and turns a disagreement between two models into a
coin-flip rather than a check against a source.

### Context assembly is capped, and the cap is a design budget

> **Superseded 2026-09-05.** The cap is `Settings.grounding_chunks = 2`, and there is
> no token budget. The throughput table below is still the right way to reason about
> prompt size, and its numbers are still the numbers — what changed is that two
> passages are bounded at roughly 1200 prompt tokens by the ingestion contract, so a
> budget had nothing left to decide. Read this section for the reasoning, not for what
> the code does.

`pack_by_tokens` ([ADR-0085](0085-tokens-are-metered-too.md),
`generation/load_balancer.py`) already packs items against a prompt-token budget with
spillover. Retrieval context assembly reuses that posture rather than inventing a
second budgeting mechanism.

The budget matters more than it looks, because sustainable throughput is
`min(TPM / prompt_tokens, RPM)` and the target is ~34 calls/min for 600 cards/hr:

| prompt size | `ministral-3b` (1.3M TPM, 750 RPM) | `ministral-8b` (625k, 188) | `ministral-14b` (937.5k, 30 RPM) |
|---|---:|---:|---:|
| 12k (today) | 108 | 52 | 30 |
| 20k | 65 | 31 | 30 |
| 30k | 43 | 21 | 30 |
| 40k | 33 | 16 | 23 |

`ministral-8b` drops below 34/min above ~18k tokens. `ministral-3b` holds to ~38k.
`ministral-14b` is RPM-capped at 30 and **can never reach 34 at any prompt size**.

**This is a budget to aim at, not a prediction.** Task 0038's build order is
deliberate on this point and this ADR does not pre-empt it: build frog, then
*measure* what prompts actually grew to from run logs, and only then sweep Mistral
concurrency at the real sizes. Picking a budget up front and hoping is the mistake
the gemini-saga was four weeks of.

### Provenance is recorded on the card

Retrieval returns chunk IDs alongside text, and the IDs are stored against the card
they grounded. "We can back with grounding why our material is high quality" is a
claim about **citability**, and a claim that cannot be checked is a slogan. Storing
the IDs is what makes a card auditable after the fact — including auditable for the
failure mode below.

### ⚠️ The corpus is the ceiling on card quality

A thin or wrong corpus produces confidently-grounded wrong cards, which are **worse
than parametric guessing** because they look sourced and because the gate is now
checking against the same bad source. This is the main risk the design takes on, it
is not mitigated by anything in this ADR, and it is why the corpus-authoring track is
supervised. Recorded here so the tradeoff is not rediscovered later as a surprise.

## Consequences

**Easier.** The truth guarantee moves upstream of the gate instead of resting on it.
A card can cite what grounded it. Cheaper, smaller, faster drafting models become
viable without quality collapse — which is the entire premise of ADR-0090.

**Harder.** Every generation call's prompt grows, and prompt size is now a throughput
input, not a detail — the table above is the whole reason the model choice is not
free. Two systems (drafter and gate) now share a dependency on corpus quality, so a
bad chunk fails silently in both directions at once. Retrieval adds a per-call latency
that did not exist, on a path already fighting for calls/minute.

**Committed to.** Prompt-size measurement before model selection, in that order.
Chunk-ID provenance on cards, which means a card outlives the chunks it cites and
something has to decide what a dangling citation means.

## Alternatives considered

**Ground the drafter only, leave the gate parametric.** Cheaper — the gate's prompts
stay small, and gate calls are on the scarcer thinking ladder. Rejected on the
coin-flip argument: a parametric gate judging a grounded draft is not a check, and
under ADR-0090 the two models are from different providers with different training,
so their disagreements would carry no information about truth.

**Keep post-hoc gating only, skip retrieval.** Zero new machinery. Rejected: it is
the status quo, and the status quo's reliability was underwritten by a model we are
leaving.

**A fixed top-k with no token budget.** Simpler. Rejected: chunk sizes vary, so a
fixed k has an unbounded token cost, and the table above shows token cost is exactly
what decides whether the target throughput is reachable at all.

> **Adopted 2026-09-05**, on the owner's decision, because the premise turned out to
> be false. Chunk sizes do *not* vary without bound: the ingestion contract rejects a
> section over `MAX_SECTION_CHARS` (2200), which is a hard check at ingest, not a
> guideline. At k=2 that caps grounding at roughly 1200 prompt tokens no matter what
> the corpus does — so the token cost of a fixed k is bounded after all, and a budget
> over it could never bind. A limit that cannot bind is the dead setting `8a8e64c`
> removed once already; keeping one here would have recreated it.
>
> The related `min_score` floor was also dropped, for a reason outside this ADR: the
> owner's commitment is that the curated corpus covers a topic before that topic
> exists in production, so there is no uncovered topic for a stray passage to be the
> best answer to. That is what a floor would have guarded against (ADR-0088's
> cross-topic risk), and it is guaranteed upstream instead.

**Record provenance as free text in the card body.** No schema change. Rejected: not
queryable, so it cannot answer "which cards did this retracted chunk ground?" — which
is the question provenance exists to answer.

## Revisit when

- Phase 4's measurement lands. If real prompt sizes push past ~38k, `ministral-3b`
  stops clearing the target rate and the model choice reopens — as does whether 2 is
  still the right depth. (The budget that would have cut depth is gone; depth is now
  the only lever, which makes this signal more directly actionable, not less.)
- A chunk is found to be wrong after cards have been generated from it. That is the
  first real test of whether stored chunk IDs are enough to act on, and the answer
  probably amends this ADR.
- Retrieval latency becomes a measurable fraction of a generation call.
