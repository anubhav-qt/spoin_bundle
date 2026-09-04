# 5. What we actually learned

> The durable conclusions, stated so that the next provider evaluation starts from
> them instead of rediscovering them. Everything here is a generalisation from
> documents 1–4; each claim names the evidence behind it.

## The five conclusions

### 1. Identify the binding constraint by direct measurement, not by inference from application runs

Four weeks and roughly ten ADRs of quota machinery were built on the inference
"we get `RESOURCE_EXHAUSTED`, therefore we are exceeding quota". A single afternoon
of controlled probing — hold exactly N requests open, sweep N — found the real
constraint and produced a table with a hard wall in it. The pipeline is a terrible
instrument: too many variables move at once, and every run costs 10 minutes.

**Rule for the next provider:** before writing any adaptive machinery, sweep the
obvious axes in isolation (concurrency, send rate, key count, token volume, prompt
size) with a standalone probe. A day of this is cheap.

### 2. An error's envelope is a claim, not a fact

Google returned `GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 500` on
keys nowhere near 500 requests, and increasingly returned scopeless
`RESOURCE_EXHAUSTED` with no `quotaId` and no `RetryInfo` at all. Believing the
label cost [ADR-0058](../adr/0058-per-minute-vs-per-day-429.md) → 
[ADR-0060](../adr/0060-unknown-429-scope-defaults-to-per-minute.md), and believing
it once more destroyed 136 of 204 cells in 60 seconds
([document 4](04-the-concurrency-ceiling.md)).

The general shape: **when a provider's error envelope and its observed behaviour
disagree, trust the behaviour.** Corroborate a scope claim against something you
measured (a short `retryDelay` cannot describe a daily limit) before taking an
expensive, persistent action on it.

### 3. Scaling the wrong axis is worse than not scaling

The key pool grew 16 → 33 → 75 → 109 keys across separate Google Cloud projects.
Under an IP-keyed concurrency limit this bought **zero** additional throughput —
and it was actively harmful: spreading one IP's traffic across 108 keys measurably
degraded it (42.2% failure vs 18.9% at 20 keys, while penalised), and maintaining
109 keys across separate projects is real operational cost.

Worse, the pool created a *false sense of headroom* that justified more
parallelism, which is the thing the ceiling punishes.

### 4. Rate and concurrency are different controls, and only one of them was the lever

The entire ADR-0086 pacing architecture — send gaps, dispatch stagger, initial
jitter, round jitter — controls *when requests are dispatched*. In-flight count was
a **consequence** of those settings and the call latency, never a controlled
quantity. Benchmark 9 succeeded by landing near the right in-flight number by
accident; a run at a *lower* send rate with uncapped concurrency failed at 73%.

**A control you care about must be measured and bounded directly.** This is the
same principle as CLAUDE.md's "the generator is trusted for taste, never for
constraints", applied to a rate limiter.

### 5. Retry behaviour is part of your load profile

Once the edge started shedding, the zero-backoff retry path (`park the cell 0s,
take the next cell`) turned a shed into **143 rejections in 2.5 minutes, ~66/min**.
Given finding #2 in [document 4](04-the-concurrency-ceiling.md) — sustained
hammering accrues a transient IP penalty that persists until the daily reset — the
retry loop was actively deepening the hole it was trying to climb out of.

A failure path that costs ~70ms per attempt is not a backoff, it is an amplifier.

## What a replacement provider must satisfy

Derived from the above, in rough priority order. This is the checklist the provider
research is measured against.

| # | Requirement | Why, from this saga |
|---|---|---|
| 1 | **A documented, quota-based limit** — RPM/RPD/TPM stated in the docs, enforced per key or per project | The entire collapse came from an *undocumented* IP-keyed limiter that no amount of correct quota accounting could see |
| 2 | **Concurrency headroom well above 3** | 3 concurrent requests caps us at ~340–450 cards/hr no matter what else is true |
| 3 | **Reliable structured output** (JSON schema / tool-calling) for 5–15k-token prompts | The pipeline sends large structured batches; [ADR-0005](../adr/0005-batch-llm-calls.md) makes this non-negotiable |
| 4 | **Informative rate-limit errors** — real `retry-after`, real scope | See conclusion #2; guessing is expensive |
| 5 | **An OpenAI-compatible or LangChain-supported endpoint** | [ADR-0002](../adr/0002-langchain-behind-an-interface.md) confines LangChain to `langchain_impl.py`; a compatible endpoint makes this a config change, not a rewrite — which is [ADR-0003](../adr/0003-free-tier-first.md)'s standing rule |
| 6 | **A model good enough for the quality gate** | The two-pass gate ([ADR-0030](../adr/0030-two-pass-quality-gate.md)) re-rates difficulty and verifies factual claims; a weak judge silently degrades the corpus |
| 7 | **A paid upgrade path that is a billing toggle** | [ADR-0003](../adr/0003-free-tier-first.md) §2 |

## What ports over unchanged

Worth stating explicitly, because it bounds how big a provider swap actually is:

- **[ADR-0002](../adr/0002-langchain-behind-an-interface.md)'s interface boundary
  holds.** Only `langchain_impl.py` imports LangChain, enforced twice (a `ruff`
  `banned-api` entry and an AST test in `tests/test_architecture.py`). A new
  provider is a new implementation of `ContentGenerator`, not a pipeline rewrite.
- **The ladder concept** ([ADR-0028](../adr/0028-key-model-quota-ladder.md)) —
  strongest model first, fall to weaker rungs — is provider-agnostic and worth
  keeping.
- **The `LoadBalancer`'s shape** ([ADR-0084](../adr/0084-per-box-load-balancer.md))
  is sound; what it should be balancing over is the open question.
- **`_WaveGate` / the in-flight cap** is useful against *any* provider with a
  concurrency limit, and harmless against one without (set it high).
- **Everything downstream of the LLM call** — the quality gate, embeddings, the
  content model, persistence — never knew which provider it was talking to.

## Open questions carried forward

1. **Which of hypotheses (a)/(b)/(c) in [document 4](04-the-concurrency-ceiling.md)
   explains the pipeline degrading at nominal-3 when the probe did not.** Unresolved.
   Relevant to a new provider only if it too has an undocumented concurrency limit.
2. **Whether the unbounded fan-out queue is a bug in its own right.** The pipeline
   dispatches far more work than any bounded gate can pass; nothing applies
   backpressure at the source.
3. **Whether local generation is viable** ([ADR-0008](../adr/0008-local-gpu-generation.md)).
   The decisive experiment — draft ~20 cards locally, push them through the existing
   gate, compare accept rate — **has still not been run**, and it would make the
   provider question much less urgent.
4. **`gemini_wave_cooldown_seconds = 2.0` is unmeasured.** If Gemini stays in the
   picture at all, a wave-mode sweep (size x cooldown) is owed.
