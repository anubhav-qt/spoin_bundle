# ADR-0008: Local GPU generation for seed content, cloud verification

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav

## Context

Generation quota is the binding constraint on the entire product (ADR-0003), and the
corpus-first launch requirement means we need thousands of cards _before_ we have users.

We have an unused asset: a local RTX 5070. A model in the 8-14B range, quantized, fits
comfortably in its VRAM and can generate continuously with **no request limit at all**.

This does not require an architectural change. Because generation is already an offline
batch job behind the `ContentGenerator` interface (ADR-0002), a local model is simply
another implementation. **This is the payoff for that abstraction.**

```
ContentGenerator
  |- GeminiContentGenerator    API, quota-bound
  |- LocalContentGenerator     RTX 5070 via vLLM/Ollama, unlimited   <- new
  \- FakeContentGenerator      tests
```

## Decision

**Use the local GPU as an offline batch content factory for our own seeded topics.
Spend scarce cloud quota on verification rather than generation.**

### Work is split by stakes, not by convenience

| Job                                 | Where     | Reasoning                                                                                           |
| ----------------------------------- | --------- | --------------------------------------------------------------------------------------------------- |
| Curriculum pass                     | **Cloud** | Highest stakes: every card in a topic inherits it. Only 1 call per topic, so quota-cheap regardless |
| Card generation, our seeded topics  | **Local** | Volume work, unlimited, errors are catchable downstream                                             |
| Card generation, user custom topics | **Cloud** | Cannot depend on a desktop being awake                                                              |
| Verification / difficulty judging   | **Cloud** | See below                                                                                           |
| Card chat                           | **Cloud** | User-facing latency; the GPU is not production infrastructure                                       |

### Spend the frontier model on judgment, not prose

Local generates abundantly; the batch judge (ADR-0005, ~20 cards per request) verifies
with Gemini. **One cloud request validates twenty locally-generated cards.**

Frontier-model _judgment_ is worth far more per token than frontier-model _prose_. This
buys most of the quality guarantee at roughly 5% of the quota cost, and it is what makes
local generation safe rather than merely cheap.

### Factual accuracy joins the quality gate

A quantized 8-14B model is meaningfully weaker than Gemini Flash at instruction-following
and, critically, at **factual accuracy**. For a product whose entire value is teaching
people true things, a hallucinated fact in a _shared_ corpus is served to every subscriber
of that topic. This is the most serious failure mode in the system.

The existing gate checks duplication, topic conformance, and difficulty. **None of them
catch "confidently wrong."** A factual-accuracy check is added, and applies with particular
force to locally-generated cards.

Human spot-checks on the first several local batches are required before trusting the
pipeline unattended.

### The GPU is offline-only, never a serving dependency

It is a machine in someone's room: power, uptime, driver updates, and ordinary personal use
of the computer all interfere. It is treated strictly as a batch factory:

```
pull work list -> generate -> validate -> push results
```

Production credentials do not live on a desktop. The runner authenticates as a service
client, or in the simplest version writes output that is imported separately. Nothing in
the read path or the user-facing write path may depend on it being online.

## Consequences

**Easier**

- The quota constraint effectively disappears for seed content, which is the hardest part
  of the corpus-first launch requirement in ADR-0003.
- Overnight runs can fill many topics at once, at zero marginal cost.
- Cloud quota is freed for the things that genuinely need it: curricula, user custom
  topics, verification, and chat.

**Harder**

- Two generation backends to keep behaviourally consistent. Prompts that work on Gemini may
  need adjustment locally, especially for structured-output adherence.
- Structured output from smaller models is less reliable. Expect a higher malformed-item
  rate within batches, which makes ADR-0005's per-item failure handling more load-bearing.
- Quality is genuinely lower. The verification layer is not optional garnish here; it is
  what makes this decision defensible.
- A new operational mode (someone runs the box) that is not automated infrastructure.

**Committed to**

- No user-facing path depends on the local GPU.
- Locally-generated cards pass the same gate as cloud-generated ones, plus factual accuracy.
- `gen_meta` records which backend produced each card, so quality can be compared between
  them and a bad batch can be traced and retired.

## Alternatives considered

**Local for everything, including user custom topics and chat.** Rejected: it makes a
desktop a production dependency, and puts the weakest model in front of users in real time.

**Cloud for everything.** The status quo. Rejected: it leaves free compute unused while
quota is the binding constraint on launch.

**Local generation without cloud verification.** Rejected. Cheapest, and the most dangerous:
unverified small-model output in a shared corpus propagates a wrong fact to every subscriber
of that topic.

**Local embeddings only, no local generation.** Already the plan (ADR-0003) and unaffected;
this ADR adds generation on top.

## Open question: specific model choice

This ADR commits to the cloud/local *split*, not to specific model names.

**Cloud side: resolved by [ADR-0028](0028-key-model-quota-ladder.md)/[0029](0029-questions-join-generator-pool.md).**
Rather than one fixed `gemini_model`, cloud generation walks an ordered fallback ladder of
models per call -- see those ADRs for the mechanism. The specific model ids were
**live-verified 2026-08-17** against 9 real Gemini keys (one call per candidate model,
checked for a real 200 response, not just presence in the API's model list -- which is
what caught `gemini-2.5-flash`/`gemini-2.5-flash-lite` looking fine in the list while
actually 404ing as "retired for new accounts"). `core/config.py`'s default ladders reflect
what was actually confirmed working on that account, not the original screenshot-derived
guess. Prompt *quality* from these models is still unverified -- this only confirms the
models respond at all.

**Local side: still fully open.** `qwen3:14b` remains a placeholder in `core/config.py` --
picked in code, never discussed. Needs a real pass (VRAM fit on the RTX 5070, quality,
structured-output reliability) before it should be treated as settled.

## Revisit when

- Measured quality of local cards (rejection rate, and engagement relative to cloud-generated
  cards on the same topics) proves unacceptable. `gen_meta` is what makes this measurable.
- We move to a paid tier and cloud generation becomes cheap enough that the operational
  overhead of running the box stops being worth it.
- Local model capability improves enough that the cloud/local split can shift further toward
  local, including the curriculum pass.
