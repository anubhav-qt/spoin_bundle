# 2. Validation plan

> Six experiments, in dependency order. **Pass/fail criteria are fixed here,
> before any data exists** — the Gemini work repeatedly reinterpreted a
> disappointing result as encouraging (Benchmark 9 was called a breakthrough and
> was superseded within a day), and writing the thresholds down first is the cheap
> defence against that.

Harness:
[`apps/api/src/spoin/probes/mistral_probe.py`](../../apps/api/src/spoin/probes/mistral_probe.py).

## Setup

```bash
docker exec -e SPOIN_MISTRAL_API_KEYS="key1,key2,key3" spoin-api-1 \
  python -u -m spoin.probes.mistral_probe models
```

Or add `SPOIN_MISTRAL_API_KEYS` to `.env` and let compose pass it through. Keys are
never logged by the harness — only their count.

**Total runtime for all six: roughly 2 hours**, most of it mandatory 60s cooldowns
between arms. Run them in order; each one can kill the ones after it.

**Model defaults changed 2026-09-04, twice.** First to `ministral-8b-2512` after
the console limits arrived; then confirmed as the *only real choice* once direct
calls showed this account gets 403/zero-limit on everything above the Ministral
tier ([doc 1](01-api-reference.md), [doc 3](03-findings.md)) — `mistral-small`,
`mistral-medium`, `magistral-*` and `mistral-large` are all unusable on this
account regardless of what the console page claims. **There is no gate-rung model
on this account.** Experiment 3b below is not one option among several any more;
it is the only way this evaluation can produce a self-contained answer.

---

## Experiment 1 — `models`

**Question:** what will these keys actually serve, and at what context length?

```bash
python -u -m spoin.probes.mistral_probe models
```

Asks `GET /v1/models` rather than trusting [document 1](01-api-reference.md)'s
table, which is compiled from third-party references and will drift. Prints each
model's id, max context and capability flags.

**Superseded by a stronger check, run 2026-09-04:** listing alone is not enough
-- `/v1/models` lists every model regardless of what this tier can call.
[Doc 3](03-findings.md) tested every plausible model with a real request instead
and found `mistral-large` (403) and every Small/Medium/Magistral variant
(429, limit=0) unusable on this account. **Use a real call, not `models`, to
qualify a candidate model on any new key** -- that is now this experiment's real
form.

**Result on the first key:** only `ministral-3b/8b/14b` and `codestral` carry real
budget. No reasoning-capable model is usable. See
[doc 3](03-findings.md#resolved--the-real-verified-model-access-for-this-key-2026-09-04)
for the full table.

*Cost: seconds.*

---

## Experiment 2 — `schema`

**Question:** does a pipeline-sized structured-output call actually return valid,
schema-conforming JSON?

```bash
python -u -m spoin.probes.mistral_probe schema --n 5
```

Three to five sequential calls at **~12,000 tokens** with a real card-batch schema.
Sequential on purpose — this is about correctness, not capacity.

**Pass:** ≥ 4/5 return `ok` (parsed, non-empty `cards` array).
**Fail:** any `bad_schema` rate above ~20% → structured output is unreliable at our
prompt weight, and capacity measurements afterwards would be measuring throughput
for calls that produce nothing usable.

This runs *before* any throughput work for exactly that reason. It is the mistake
the Gemini work avoided by luck rather than design.

*Cost: ~2 minutes.*

---

## Experiment 3 — `concurrency` ← **the decisive one**

**Question:** does Mistral shed on concurrency, and if so, where is the wall?

```bash
python -u -m spoin.probes.mistral_probe concurrency --min 1 --max 8
```

Holds *exactly* N requests open — each worker calls, awaits the full response,
calls again — for 6 minutes per arm, sweeping N = 1…8 with 60s cooldowns. This is
`inflight_sweep.py` repointed, and it is the experiment that would have saved the
Gemini work four weeks.

The Gemini result for comparison
([gemini-saga doc 4](../gemini-saga/04-the-concurrency-ceiling.md)):

| N | failure |
|---|---|
| 2 | 1.5% |
| 3 | 1.2% |
| **4** | **53.6%** |
| 5 | 48.4% |

**RESULT (2026-09-04): PASS.** N=2..5 swept, 641 calls, zero 429s at any
concurrency, throughput climbing monotonically (0.29 -> 0.59 good/s). No wall in
the range that killed Gemini. Full data: [doc 3](03-findings.md#experiment-3--concurrency-2026-09-04-1053-1121-utc).
N=6-8 not yet run; not needed to conclude "PASS" against this experiment's own
threshold, worth doing before treating the ceiling as fully bounded.

Watch `first429` as much as the failure rate: a clean rate with a late first-429 is
degradation, not headroom.

*Cost: ~55 minutes for N=1…8.* Run `--min 2 --max 5` first (~25 min) if you want the
answer sooner; that brackets Gemini's wall.

---

## Experiment 3b — drafting quality on the small models ← **now the load-bearing experiment**

**Question:** is `ministral-8b` (or `3b`/`14b`) good enough to draft cards that
survive our own quality gate?

This experiment did not exist before the console limits arrived, and after
[doc 3's](03-findings.md) direct-call results it is no longer just important — it
is the only experiment that can produce a self-contained yes on this account.
**Every model on this tier with real budget is a small completion model**; there
is no reasoning-capable model to gate with even if we wanted one, so "draft on
Mistral, judge with the existing Gemini gate" is not a methodology choice, it is
the only configuration this account supports.

Method — the same shape as the untested local-generation experiment in
[ADR-0008](../adr/0008-local-gpu-generation.md), and worth running both ways:

1. Draft ~20 cards for a known subtopic with `ministral-8b-2512`.
2. Push them through the **existing Gemini quality gate** unchanged
   ([ADR-0030](../adr/0030-two-pass-quality-gate.md)) — difficulty re-rating plus
   factual verification.
3. Compare the accept rate against Gemini-drafted cards on the same subtopic.

**Pass:** accept rate within ~10 points of the Gemini baseline → the capacity is
usable and the provider is live.
**Marginal:** 10–25 points below → `ministral-14b` (30 calls/min, just under our
need) or a hybrid becomes the shape, not 8b alone.
**Fail:** more than ~25 points below → Mistral's capacity is on models that cannot
do the job, which is the same as having no capacity. The cheap models being fast
is not a finding; them being *good enough* is.

Deliberately uses the Gemini gate rather than a Mistral one: changing the drafter
and the judge simultaneously measures nothing.

*Cost: ~30 minutes, and it needs a real pipeline invocation rather than the probe.*

---

## Experiment 4 — `keycount`

**Question:** is the limit per-key or per-IP?

```bash
python -u -m spoin.probes.mistral_probe keycount --inflight 3 --counts 1 3 5
```

Same total load, spread over 1, 3, then 5 keys. **This is the question that
retroactively invalidated a 109-key pool**, so it is worth its 20 minutes.

**Per-key limit:** failure drops as key count rises → pooling works, and the
[ADR-0084](../adr/0084-per-box-load-balancer.md) balancer has something real to
balance.
**Per-IP limit:** failure is flat across all three → **more keys buy nothing**, and
the entire pooling strategy is dead on Mistral exactly as it was on Gemini.
**Worse with more keys:** the Gemini "penalised IP" signature — spreading traffic
across many keys was actively harmful. Strongest possible stop signal.

Needs ≥ 5 keys to be meaningful; with 3 it still distinguishes flat from sloped.

**Lower priority than it was.** [Doc 1](01-api-reference.md) shows one key already
covers the workload (73 calls/min against a need of 34, across two per-model
budgets), so this no longer gates the decision — it is now about whether headroom
*beyond* one key exists at all, which matters only if we later want to run several
topics concurrently again.

*Cost: ~20 minutes.*

---

## Experiment 5 — `soak`

**Question:** does a setting that looks clean stay clean?

```bash
python -u -m spoin.probes.mistral_probe soak --inflight <best from exp 3> --seconds 1800
```

30 minutes at the best concurrency found. **This exists because Gemini's rolling
semaphore held perfectly clean for five minutes and then shed hard, and
batch-and-pause lasted 8.5** — an arm shorter than that scores both as a pass.

**Pass:** `first429 = never`, failure flat across the whole run.
**Fail:** any 429 onset partway through → there is a slow-accruing penalty, which
is the hardest failure mode to design around and the one that most resembles what
we just left.

*Cost: 30 minutes.*

---

## Decision table

| Outcome | Meaning | Next step |
|---|---|---|
| **Exp 3: PASS (confirmed)** | No concurrency wall through N=5 | Live -- unblocks everything below |
| Exp 3b passes | Mistral drafts survive the Gemini gate | Write `HybridContentGenerator` (Gemini thinking + Mistral generator rungs, per the plan discussed 2026-09-04); ADR the provider choice. **No account scaling needed** |
| Exp 3b fails | Capacity is on models that cannot draft acceptably | Stop, or restrict Mistral to the ASCII-fetch sub-task only (lower risk, see doc 1) |
| Exp 5 degrades | Slow-accruing penalty (Gemini's second failure mode) | Treat as fail even though exp 3 passed -- a clean short sweep is not the same fact as a clean long one |
| Exp 4 flat | Per-IP limit, no per-key headroom | Fine at current scale (one key already covers the workload); relevant only for future multi-topic concurrency |
| Exp 2 fails | ~~Schema unreliable~~ already confirmed reliable (5/5, then 641 calls with only isolated bad_schema) | n/a |

## What we deliberately are *not* doing yet

- **Not writing `MistralContentGenerator`.** It is maybe a day's work behind the
  existing interface, and writing it before experiment 3 would be building on the
  same assumption that cost four weeks last time.
- **Not creating 20 accounts.** The console limits made this moot: one key covers
  the workload. Three to five still makes experiment 4 meaningful, but the
  multi-account strategy — and its ToS exposure — is off the table unless something
  later demands it.
- **Not touching the Gemini path.** It works, at ~220–340 cards/hr. Mistral has to
  beat that on measured evidence before anything is switched.

## Recording results

When the first probe runs, create `03-findings.md` here with the raw tables — not
a summary. [gemini-saga doc 4](../gemini-saga/04-the-concurrency-ceiling.md) is
useful today precisely because it kept the numbers, and every config constant in
`config.py` that cites a measurement is traceable to one.
