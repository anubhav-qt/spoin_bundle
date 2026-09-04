# 1. The good era

> **2026-08-15 → 2026-08-30.** Runs 1 through 8. The pipeline was built, scaled to
> five topics at a time, and left to run unattended overnight. Tens of thousands of
> real cards. Every problem in this period was solved by *better quota accounting*,
> which is exactly why the next period was so confusing.

## The founding assumptions

Two ADRs written on day one set the shape of everything that followed.

**[ADR-0003](../adr/0003-free-tier-first.md) — free-tier-first.** Every piece of
infrastructure starts on a free tier, and no accommodation to a free tier may
require a rewrite to undo. Paying is a config change, not a migration. This is why
the project accumulated API keys rather than a bill, and it is a good rule that
held up — the thing it did not anticipate is a free-tier limit that *more keys
cannot buy your way around*.

**[ADR-0005](../adr/0005-batch-llm-calls.md) — batch every LLM call.** Every
LLM-facing interface method takes a collection, never a single item, enforced in
`tests/test_architecture.py`. The stated reason: the free tier meters *requests*,
not tokens, so one 15-card call strictly beats 15 single-card calls. The rule was
right. **The reason was false**, and it took until 2026-09-03
([ADR-0085](../adr/0085-tokens-are-metered-too.md)) to find out that 250,000
tokens per minute per project per model is also metered — by which point the
pipeline's habit of sending very large structured-output batches was load-bearing,
and those large batches turn out to matter for reasons beyond tokens (see
[document 4](04-the-concurrency-ceiling.md)).

## The ladder

[ADR-0028](../adr/0028-key-model-quota-ladder.md) (2026-08-17) is the spine of the
whole Gemini integration: a grid of `(api_key, model)` **cells**, walked as a
*ladder* — strongest model first, falling to weaker rungs only when the strong ones
have nothing left. Two ladders over the same physical keys, one for generation and
one for "thinking" (planning, judging, verification), because the thinking models
have far tighter limits (rpm 5 / rpd 20) than the generation ones.

Everything for the next two weeks is a refinement of how to choose the next cell.

## The runs

| Run | Date | What it proved | Scale |
|---|---|---|---|
| [1](../architecture/generation-pipeline-test-run.md) | 08-21 | First full end-to-end multi-topic run. 100% success. | 2 topics, 1,065 cards, 1,056 questions |
| [2](../architecture/generation-pipeline-run-2-benchmark.md) | 08-21 | [ADR-0047](../adr/0047-removal-of-legacy-concurrency-semaphore.md) removed a global semaphore ("the 40-key Ferrari in a school zone"). | 3 topics, 3,939 cards, 3,101 questions |
| [3](../architecture/generation-pipeline-run-3-benchmark.md) | 08-22/23 | Multi-domain scaling — German, FastAPI, Kubernetes, Claude Code, Study Abroad. Pipeline is not CS-specific. | 5 topics |
| [4](../architecture/generation-pipeline-run-4-benchmark.md) | 08-24 | The redraft loop ([ADR-0057](../adr/0057-redraft-loop-for-gate-attrition.md)) and the failed-vs-rejected stuck-guard, live. | 2 topics |
| [5](../architecture/generation-pipeline-run-5-benchmark.md) | 08-26 | Started as an incident: a `QuotaExhaustedError` that disagreed with Google's own dashboard. Root-caused to two bugs → [ADR-0060](../adr/0060-unknown-429-scope-defaults-to-per-minute.md), [ADR-0061](../adr/0061-refund-grants-that-never-became-requests.md). | 3 sequential topics |
| [6](../architecture/generation-pipeline-run-6-benchmark.md) | 08-28 | **Five topics overnight, unattended, to 100%.** The high-water mark for "you can start it and walk away". | 5 topics, 5/5 completed |
| [7](../architecture/generation-pipeline-run-7-benchmark.md) | 08-30 | [ADR-0074](../adr/0074-key-per-subtopic-scheduling.md)'s key-per-subtopic scheduler. CockroachDB end to end in **18m 50s**. | 1 topic, 35/35 subtopic-tiers |
| [8](../architecture/generation-pipeline-run-8-benchmark.md) | 08-30 | The full production stress test. | 6 topics complete + 1 at 81%, **4,139 cards + 1,606 questions in one day**, 33 keys |

Run 8's per-topic numbers are the benchmark everything later is measured against:
Linear Algebra 264 cards in 11m45s (22.5 cards/min), CockroachDB 492 cards in
15m13s (32.3 cards/min).

## What the 429s looked like then

Rate limits were a constant presence, but they were *legible*. A 429 arrived with
an envelope naming its `quotaId` and often a `RetryInfo.retryDelay`, and the
distinction between the two kinds mattered enough to get its own ADR:

- **[ADR-0058](../adr/0058-per-minute-vs-per-day-429.md) (08-25)** — a per-minute
  throttle and a per-day exhaustion are *different facts*, read off the payload. A
  per-minute 429 parks a cell for seconds; a per-day 429 spends it until tomorrow.
  Confusing them wastes either a whole day of a key or hundreds of doomed retries.
- **[ADR-0060](../adr/0060-unknown-429-scope-defaults-to-per-minute.md) (08-26)** —
  ADR-0058 had defaulted *unknown* scope to per-day and called it conservative.
  Measured cost of that choice: **65 of 66 cells slammed inside 100 seconds**,
  because the pipeline's gate fan-out crowds the RPM ceiling and every simultaneous
  throttle got read as an exhaustion. Reversed: ambiguity is now a throttle.

That reversal is the first appearance of a pattern that dominates the rest of the
saga: **Google increasingly returns scopeless `RESOURCE_EXHAUSTED` with no
`quotaId` and no `RetryInfo` at all.** At the time this looked like an API-surface
annoyance to be defended against. It was actually the first symptom of a different
limiter entirely — one that does not think in quotas and therefore has no quota to
name.

## The scheduling arc

Between Runs 6 and 8 the *unit of key ownership* kept getting coarser, each step
chasing the same goal — stop many callers from hitting the same cell at once:

1. **Per-call selection** (Runs 1–6). Every request scans the whole grid for the
   least-spent cell.
2. **[ADR-0040](../adr/0040-per-cell-call-serialization.md) (08-19)** — serialize
   actual network calls per `(key, model)` cell with a lock.
3. **[ADR-0074](../adr/0074-key-per-subtopic-scheduling.md) (08-30)** — one key per
   subtopic *group*, held across that group's whole card run. Run 7's 18m50s topic.
4. **[ADR-0065](../adr/0065-quota-governor-fairness-accounting-and-terminal-states.md) (08-28)**
   — the governor spreads load least-spent-first, refunds refused calls, learns each
   cell's real rpm by AIMD, and **names why it stopped**: `DailyQuotaExhaustedError`,
   `AllCellsThrottledError`, `AllModelsUnavailableError` are three genuinely
   different failures and folding them together makes a provider outage read as a
   budget problem.

At the end of August this was a mature, well-reasoned system, and it worked. The
next document is about the fortnight in which it completely stopped working and
none of this machinery could explain why.
