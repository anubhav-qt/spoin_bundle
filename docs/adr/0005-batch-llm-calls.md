# ADR-0005: Batch every LLM call; never economize on tokens

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav, Mayank

## Context

Gemini's free tier meters **requests per day and per minute**, not tokens. Our binding
constraint is therefore the *number of API calls*, and the size of each call is nearly
free by comparison.

This inverts the instinct most developers bring from paid LLM usage, where token count
is the cost driver and terse prompts and outputs are a virtue. Here, terseness buys
nothing and costs capability.

The previous iteration of this product died on exactly this constraint: a pool-fill
worker issuing one request per card could never fill the content pool within the daily
request cap.

## Decision

**Design every LLM interaction as a batch, from the start.**

Two rules:

1. **Never economize on output size.** Adding fields to a structured output is
   effectively free. If a field is useful, ask for it.
2. **Never issue N requests where 1 will do.** Batch size is a tuning parameter, not
   an afterthought, and every LLM-calling component takes a list rather than a single item.

### Applied

| Operation | Naive | Batched | Effective gain |
|---|---|---|---|
| Card generation | 1 request per card | ~10 cards per request | ~10x daily output |
| Difficulty verification | 1 request per card | ~20 cards per request | ~20x, makes the gate affordable |
| Topic canonicalization judge | 1 request per pair | queue pairs, judge in batches | permanently cached after |

The generation job is built around `generate_batch(topic, difficulty, n)` from day one.
There is no single-card entrypoint to retrofit later.

## Consequences

**Easier**
- Roughly an order of magnitude more content per day on the same free tier. This is the
  difference between the corpus filling and not filling, so it is not an optimization.
- The quality gate becomes affordable enough to run on **every** card rather than a sample.
- We can ask for richer structured output (`summary`, self-assessments, metadata) without
  weighing each field against cost.

**Harder**
- **Partial failure is now the normal case.** If 3 of 10 cards in a batch are malformed,
  the other 7 must still land. Every batch call needs per-item validation and per-item
  failure handling. A batch that fails atomically wastes a scarce request.
- Larger outputs risk truncation against output token limits. Batch size must be tuned
  against the actual limit, with a retry-at-smaller-size path.
- Debugging is harder: a bad card is now one of twenty in a trace. LangSmith
  (ADR-0002) is what keeps this tractable.

**Committed to**
- Every LLM-calling interface takes a collection. Single-item calls are a batch of one,
  never a separate code path.

## Alternatives considered

**One request per item, accept lower throughput.** Simpler code, trivial error handling.
Rejected: it is the specific failure that killed the previous attempt. The corpus
cannot fill at that rate.

**Batch only generation, keep verification single.** Would leave the quality gate
unaffordable, so it would get sampled or dropped, which defeats its purpose.

**Skip the quality gate to save requests.** Rejected. Bad cards are permanent: they sit
in a shared corpus and are served to every user on that topic. The cost of a bad card
is far higher than one request.

## Revisit when

- We move to a paid tier metered by tokens rather than requests. Then the economics
  invert and batch sizes should be re-evaluated (though batching will likely still win
  on latency and overhead).
- Output truncation becomes a frequent failure mode, indicating batch sizes are tuned
  too aggressively.
