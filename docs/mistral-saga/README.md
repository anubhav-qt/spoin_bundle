# The Mistral Saga

> **Started 2026-09-04.** Evaluating Mistral as a replacement or supplement for
> Gemini in the generation write path. **Status: nothing validated yet.** The
> harness is built and waiting on keys.
>
> This directory is deliberately started *before* any commitment, which is the
> single biggest process change from [`docs/gemini-saga/`](../gemini-saga/README.md).
> That one had to be written backwards from four weeks of dead ends. This one is
> written forwards.

## Read in order

| # | Document | Covers |
|---|---|---|
| 1 | [API reference](01-api-reference.md) | Models, endpoints, structured output, limits — what the docs say, and what they conspicuously do not |
| 2 | [Validation plan](02-validation-plan.md) | The six experiments, in order, with pass/fail criteria fixed **before** the data arrives |
| 3 | [Findings](03-findings.md) | Raw results as they land — already contains a real correction to doc 1's console-table reading |

## Why we are here

[Gemini saga document 6](../gemini-saga/06-provider-alternatives.md) surveyed
thirteen providers against our workload (~114M tokens/day at a modest 8-hour rate,
5–17k tokens per call, structured output mandatory) and found that **no free tier
fits on a single key** — the most generous published figure was short by ~3.5x.

**Real, verified access is narrower than the console page claims — and it settles
the shape of the whole evaluation.** A direct call to every plausible model (not
the console's Organization Limits table, which turned out to list rate limits for
models this account is 403'd on) found that **only the Ministral family and
Codestral carry real budget.** `mistral-large` is tier-gated (403); every
`mistral-small`/`mistral-medium`/`magistral-*` variant is permanently rate-limited
to zero (429, `x-ratelimit-limit-req-minute: 0`). See
[doc 1](01-api-reference.md) and [doc 3](03-findings.md).

**This account has no reasoning-capable model at any usable rate.** So the
question is no longer "which model gates" — there is no gate-rung candidate here
at all. The only viable shape is: **Mistral drafts (`ministral-8b`, 52 of our
calls/min against a need of ~34), the existing Gemini gate judges.** That is not a
methodology choice; it is the only configuration this tier supports.

Two questions remain, and one is now load-bearing:

1. ~~Does Mistral have the same undocumented, IP-keyed concurrency shedder Gemini
   turned out to have?~~ **Answered 2026-09-04: no.** Swept N=2..5, 641 calls, zero
   429s, throughput rising with concurrency instead of collapsing. See
   [doc 3](03-findings.md).
2. **Are `ministral-8b`/`14b` good enough to draft cards that survive the Gemini
   gate?** This is now the ONLY experiment the evaluation rests on.

## The rule this directory exists to enforce

> **Measure the provider before building on it, not after.**

Gemini's binding constraint — a hard wall between 3 and 4 concurrent requests from
one source IP, invisible to every quota mechanism we built — took four weeks to
find through pipeline runs and one afternoon to find with a controlled sweep. The
sweep is now the first thing we do, not the last.

Concretely, before *any* production code is written against Mistral:

1. Its concurrency behaviour is swept and the wall (if any) is located.
2. Structured output is proven at pipeline prompt sizes, not toy ones.
3. The result is written down here, whether it is good news or bad.

## The harness

[`apps/api/src/spoin/probes/mistral_probe.py`](../../apps/api/src/spoin/probes/mistral_probe.py)
— committed rather than left in a scratchpad, because the Gemini probes were kept
in one and were nearly lost even though their numbers are the only evidence behind
several config constants.

It calls `https://api.mistral.ai/v1/chat/completions` directly over `httpx` rather
than through LangChain, deliberately: a client wrapper adds its own retries and
timing, and this measures the transport. It reads no database and cannot touch
`spoin_db_2`.

```bash
docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe models
```

Five commands — `models`, `schema`, `concurrency`, `keycount`, `soak` — described
in [document 2](02-validation-plan.md).

## What is needed to proceed

**1 Mistral API key** is now enough for the two decisive experiments (concurrency
and drafting quality) — the console limits removed the need for a pool. **3–5 keys**
still make experiment 4 (per-key vs per-IP) meaningful, which is worth knowing for
later multi-topic concurrency but no longer gates the decision.

Exported as `SPOIN_MISTRAL_API_KEYS` (comma-separated). The harness logs only the
key *count*, never a key.
