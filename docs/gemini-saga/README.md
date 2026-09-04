# The Gemini Model Saga

> **Span:** 2026-08-15 → 2026-09-04. **Provider:** Google Gemini free tier, via
> `langchain-google-genai`. **Outcome so far:** a working pipeline that cannot be
> made to run *reliably* at any useful concurrency, for a reason that turned out
> not to be about quota at all.

This directory is the narrative history of one dependency: Google's Gemini free
tier, from the day the pipeline first called it to the day we started looking for
somewhere else to call. It exists because the reasoning is spread across ~25 ADRs,
9 benchmark documents, 4 handoffs and a debugging note, and none of them tells the
story end to end. **The ADRs remain the source of truth for every decision** — this
is the connective tissue between them, written so that a new session (or a new
provider evaluation) does not have to re-derive four weeks of dead ends.

## Read in order

| # | Document | Covers |
|---|---|---|
| 1 | [The good era](01-the-good-era.md) | 2026-08-15 → 08-30. Runs 1–8. It worked, and we thought we understood why. |
| 2 | [The collapse](02-the-collapse.md) | 2026-08-30 → 09-03. Key boxes, the load-balancer rewrite, Benchmarks 1–8: ten hours, zero cards. |
| 3 | [The pacing breakthrough](03-the-pacing-breakthrough.md) | 2026-09-04, early. Benchmark 9: 426 cards in 38 minutes, and why it was less of a fix than it looked. |
| 4 | [The concurrency ceiling](04-the-concurrency-ceiling.md) | 2026-09-04. The real constraint, found by direct measurement. Benchmark 10, the in-flight semaphore, the wave gate. |
| 5 | [What we actually learned](05-what-we-learned.md) | The durable conclusions, the open questions, and what a replacement provider must satisfy. |
| 6 | [Provider alternatives](06-provider-alternatives.md) | What the workload actually needs, why free tiers fail it, and the three honest options. |

## The one-paragraph version

We built the pipeline against Gemini's free tier assuming the binding constraint
was **quota** — requests per minute and per day, metered per key per model — and
built increasingly sophisticated machinery to spread load across a growing pool of
API keys (16 → 33 → 75 → 109). That machinery worked, and Runs 1–8 produced tens of
thousands of real cards. Then it stopped working, completely, and no amount of
additional quota accounting brought it back. On 2026-09-04 direct probing found
why: **Google's free-tier edge gateway sheds on concurrency — how many requests
from your source IP are simultaneously awaiting a response — not on send rate, key
count, or token volume.** The wall sits between 3 and 4 concurrent requests, and it
is a wall, not a gradient (≤3 open → ~1% failure; 4 open → 53%). Every key in the
pool shares it, because it is keyed to the IP. **The entire key-pool strategy —
four weeks and ten ADRs of it — was buying a resource that was never the scarce
one.** Three concurrent requests is the ceiling, so the pool's only remaining
purpose is per-key daily quota, and throughput is capped at roughly what a single
well-paced stream can do.

## Why this ends in a provider search

The ceiling is a property of Google's free tier and our egress IP, not of our code.
[Document 6](06-provider-alternatives.md) evaluates where else to go — and finds
that no free tier fits a 12k-token call on a single key, so every one of them would
require the same multi-key pooling that this saga suggests is what triggered the
limiter in the first place. The two experiments worth running before choosing
anything are named at the end of that document.

## Related source-of-truth documents

- **ADRs:** [0003](../adr/0003-free-tier-first.md) (free-tier-first),
  [0005](../adr/0005-batch-llm-calls.md) (batch every call),
  [0028](../adr/0028-key-model-quota-ladder.md) (the key/model ladder),
  [0058](../adr/0058-per-minute-vs-per-day-429.md) /
  [0060](../adr/0060-unknown-429-scope-defaults-to-per-minute.md) (429 classification),
  [0065](../adr/0065-quota-governor-fairness-accounting-and-terminal-states.md) (the governor),
  [0082](../adr/0082-fixed-key-boxes-per-topic.md) (key boxes),
  [0084](../adr/0084-per-box-load-balancer.md) (the load balancer),
  [0085](../adr/0085-tokens-are-metered-too.md) (token metering),
  [0086](../adr/0086-concurrency-staggering-and-initial-dispatch-jitter.md) (pacing).
- **Benchmarks:** [Run 1](../architecture/generation-pipeline-test-run.md) through
  [Run 8](../architecture/generation-pipeline-run-8-benchmark.md) in `docs/architecture/`.
- **Debugging note:** [rate-limit-load-balancer-debugging.md](../notes/rate-limit-load-balancer-debugging.md).
- **Handoffs:** [ADR-0084 send gaps](../handoff/adr-0084-send-gap-benchmarks.md),
  [ADR-0085 concurrency bursts](../handoff/adr-0085-concurrency-burst-benchmarks.md),
  [ADR-0086 Benchmark 9](../handoff/adr-0086-breakthrough-benchmark.md),
  [the IP concurrency ceiling](../handoff/ip-concurrency-ceiling-and-inflight-semaphore.md).
