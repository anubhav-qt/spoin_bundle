# 3. Findings

> Raw results, in the order run. One key, from the account whose Organization
> Limits console produced [doc 1](01-api-reference.md)'s numbers.

## Experiment 1 — `models` (2026-09-04)

```
docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe models
```

**46 models visible.** Full output kept below because the console limits table in
[doc 1](01-api-reference.md) names several IDs that turn out not to exist for this
key at all.

```
codestral-2508                         ctx=256000   caps=completion_chat,function_calling,completion_fim
codestral-embed                        ctx=8192     caps=-
codestral-embed-2505                   ctx=8192     caps=-
codestral-latest                       ctx=256000   caps=completion_chat,function_calling,completion_fim
labs-leanstral-1-5                     ctx=262144   caps=completion_chat,function_calling,reasoning,vision,unified_resources
labs-leanstral-1-5-1                   ctx=262144   caps=completion_chat,function_calling,reasoning,vision,unified_resources
magistral-medium-latest                ctx=32768    caps=-
magistral-small-latest                 ctx=262144   caps=completion_chat,function_calling,reasoning,vision
ministral-14b-2512                     ctx=262144   caps=completion_chat,function_calling,fine_tuning,vision
ministral-14b-latest                   ctx=262144   caps=completion_chat,function_calling,fine_tuning,vision
ministral-3b-2512                      ctx=131072   caps=completion_chat,function_calling,fine_tuning,vision
ministral-3b-latest                    ctx=131072   caps=completion_chat,function_calling,fine_tuning,vision
ministral-8b-2512                      ctx=262144   caps=completion_chat,function_calling,fine_tuning,vision
ministral-8b-latest                    ctx=262144   caps=completion_chat,function_calling,fine_tuning,vision
mistral-code-fim-latest                ctx=256000   caps=completion_chat,function_calling,completion_fim
mistral-code-latest                    ctx=256000   caps=completion_chat,function_calling,completion_fim
mistral-embed                          ctx=8192     caps=-
mistral-embed-2312                     ctx=8192     caps=-
mistral-medium                         ctx=32768    caps=-
mistral-medium-2604                    ctx=32768    caps=-
mistral-medium-3                       ctx=32768    caps=-
mistral-medium-3-5                     ctx=32768    caps=-
mistral-medium-3.5                     ctx=32768    caps=-
mistral-medium-latest                  ctx=32768    caps=-
mistral-moderation-2603                ctx=131072   caps=classification,moderation
mistral-ocr-2512 / -3 / -3-0 / -4 / -4-0 / -4-1 / -latest   ctx=16384   caps=function_calling,vision,ocr
mistral-small-2603                     ctx=262144   caps=completion_chat,function_calling,reasoning,vision
mistral-small-latest                   ctx=262144   caps=completion_chat,function_calling,reasoning,vision
mistral-vibe-cli-fast                  ctx=262144   caps=completion_chat,function_calling,reasoning,vision
mistral-vibe-cli-latest                ctx=32768    caps=-
mistral-vibe-cli-with-tools            ctx=32768    caps=-
voxtral-* (transcription/TTS)          -- not relevant
```

### Three things this corrects in doc 1

1. **Confirmed by direct call: `mistral-large` is tier-gated, not just absent from
   this key's model list.**
   ```
   POST /v1/chat/completions model=mistral-large-2512  -> 403 tier_not_allowed
     "This model is not available in your subscription tier"
   POST /v1/chat/completions model=mistral-large-latest -> 403 tier_not_allowed
   ```
   So doc 1's proposed gating rung — "draft on `ministral-8b-2512` (52/min) + gate
   on `mistral-large-2512` (21/min) = 73/min" — is wrong, and the console's
   Organization Limits page **lists rate limits for models this account cannot
   call at all.** Treat every row on that page as unverified until a real call to
   that exact model succeeds -- the table describes a rate-limit catalog, not this
   account's actual model access.
2. **`mistral-medium-latest` and `magistral-medium-latest` both returned `429
   rate_limited` on the very first call of the session** -- not after sustained
   load, immediately. Both are separate model IDs with (per doc 1) independent
   per-model budgets, so a first-call 429 on two unrelated models in the same
   few seconds is not explained by either model's own quota being spent. Two
   readings, not yet distinguished: **(a)** these two rungs share an RPS=1 budget
   that is *also* shared with something else this account just called (the
   `schema` experiment's 5 calls to `ministral-8b-2512` moments earlier), which
   would mean the "independent per-model budget" reading in doc 1 is wrong for at
   least these two models; or **(b)** an account-wide burst limit exists
   independent of the per-model table entirely. A retry after a 65s cooldown is in
   flight; see below.
3. **`mistral-medium-latest` has a 32,768-token context**, not the 256k that
   [doc 1](01-api-reference.md)'s Models table claimed from third-party sources.

### RESOLVED — the real, verified model access for this key (2026-09-04)

Doc 1's console table and `/v1/models` both turned out to be unreliable guides to
what this key can actually call: the console lists rate limits for models the key
gets 403'd on, and `/v1/models` lists every model regardless of tier. **The only
trustworthy source is a real call**, checked against the `x-ratelimit-limit-*`
response headers (the limit itself, not just whether the last call succeeded).

Tested every plausible model directly:

| Model | Result | TPM | RPM |
|---|---|---:|---:|
| `ministral-3b-2512` / `-latest` | **200 OK** | 1,300,000 | 750 |
| `ministral-8b-2512` / `-latest` | **200 OK** | 625,000 | 188 |
| `ministral-14b-2512` / `-latest` | **200 OK** | 937,500 | 30 |
| `codestral-2508` / `-latest` | **200 OK** | 625,000 | 125 |
| `mistral-code-latest` | **200 OK** | 625,000 | 125 |
| `mistral-code-fim-latest` | **200 OK** | 625,000 | 125 |
| `labs-leanstral-1-5(-1)` | 403 tier-gated | — | — |
| `magistral-small-latest` | 429, **limit=0** | — | 0 |
| `mistral-small-2603` / `-latest` | 429, **limit=0** | — | 0 |
| `mistral-medium-latest` / `-2604` / `-3` / `-3-5` | 429, **limit=0** | — | 0 |
| `magistral-medium-latest` | 429, **limit=0** | — | 0 |
| `mistral-large-2512` / `-latest` | 403 tier-gated | — | — |
| `mistral-vibe-cli-*` | 429, **limit=0** | — | 0 |
| `mistral-moderation-2603` | 400 invalid model | — | — |

**This resolves finding 2 above completely.** It was never a burst or a shared
budget window — `x-ratelimit-limit-req-minute: 0` is the account's *permanent*
allocation for that model on this tier, identical in effect to the 403s, just
surfaced as a rate limit instead of a subscription error. No amount of waiting
clears a limit of 0.

**The real picture for this account's tier:**

- **Usable (real, non-zero budget): only the Ministral family + Codestral/vibe-code
  variants of Codestral.** Six model IDs, three underlying models
  (`ministral-3b`, `ministral-8b`, `ministral-14b`, `codestral`).
- **Blocked entirely, tier-gated (403):** `mistral-large`, `labs-leanstral`.
- **Blocked entirely, zero-limit (429):** every Small, Medium, and Magistral
  variant, plus `mistral-vibe-cli`.
- **This account has NO model capable of independent reasoning/judgement work at
  a usable rate.** Every model with a real budget is a small, fast completion
  model. There is no gate-rung candidate on this key at all.

**Doc 1's console table is now confirmed unreliable as a source and needs a
correction pass**, not just the two entries already flagged — it names
`mistral-large-2512` a working rate limit despite the account being 403'd on it,
and does not distinguish "this account can call this model" from "this model has
a public rate limit." Both need fixing; see "Next steps".

## Experiment 2 — `schema` (2026-09-04)

```
docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe schema --n 5
```

Model: `ministral-8b-2512`. Prompt: ~12,000 tokens (48,162 chars), real card-batch
JSON schema, `strict: true`.

```
call 1: ok in 6.3s
call 2: ok in 8.3s
call 3: ok in 7.4s
call 4: ok in 9.7s
call 5: ok in 6.5s
```

**5/5 `ok`. Pass**, well clear of the ≥4/5 threshold in
[doc 2](02-validation-plan.md). Every call returned a non-empty, schema-conforming
`cards` array on the first attempt. Latency 6.3–9.7s, comparable to Gemini's
structured-output calls (7–17s in
[gemini-saga doc 4](../gemini-saga/04-the-concurrency-ceiling.md)).

This says nothing yet about whether the *content* is good enough — that is
experiment 3b, still to run — only that the model reliably holds the shape at
pipeline prompt weight.


## Experiment 3 — `concurrency` (2026-09-04, 10:53-11:21 UTC)

```
docker exec spoin-api-1 python -u -m spoin.probes.mistral_probe concurrency --min 2 --max 5 --model ministral-8b-2512
```

One key. `ministral-8b-2512`. Bracketed sweep (N=2..5) around Gemini's known wall
at N=4, 6 minutes/arm, 60s cooldown between arms, ~12k-token structured prompts.

```
inflight=2   n=108   fail= 1.9%   good/s=0.29   first429=never   lat[min=4.8 med=6.6 p95= 8.8 max=10.4]   bad_schema=2, ok=106
inflight=3   n=147   fail= 0.0%   good/s=0.40   first429=never   lat[min=5.3 med=7.2 p95=10.0 max=11.9]   ok=147
inflight=4   n=165   fail= 0.6%   good/s=0.44   first429=never   lat[min=5.0 med=8.1 p95=15.6 max=24.7]   bad_schema=1, ok=164
inflight=5   n=221   fail= 2.3%   good/s=0.59   first429=never   lat[min=5.6 med=7.8 p95=11.4 max=15.4]   bad_schema=5, ok=216
```

**No wall through N=5. `first429=never` on every arm — zero 429s in 641 total
calls.** This is the direct comparison point against Gemini
([gemini-saga doc 4](../gemini-saga/04-the-concurrency-ceiling.md)):

| N | Gemini failure | Gemini 429s | Mistral failure | Mistral 429s |
|---|---:|---:|---:|---:|
| 2 | 1.5% | 0 | 1.9%* | 0 |
| 3 | 1.2% | 0 | 0.0% | 0 |
| **4** | **53.6%** | **220** | **0.6%*** | **0** |
| 5 | 48.4% | 200 | 2.3%* | 0 |

\* Every Mistral "failure" here is `bad_schema` — a 200 response whose JSON didn't
parse into the expected `cards` array — never a throttle. **These are not the
same fact and must not be read the same way** (the module docstring's whole point):
a `bad_schema` count is a content-quality signal about `ministral-8b`'s adherence
under load, not evidence of any rate limiting.

**Throughput climbed monotonically with concurrency** (0.29 -> 0.40 -> 0.44 ->
0.59 good/s) rather than falling off a cliff. The one sign of load at all is
latency spread widening at N=4 (p95 15.6s, max 24.7s, against N=3's 10.0/11.9) --
consistent with the server queuing internally rather than an edge gateway
shedding connections. That is a fundamentally different (and much better) failure
character than Gemini's hard wall.

**Reading against [doc 2](02-validation-plan.md)'s fixed thresholds: PASS**, and
by a wide margin -- failure stayed under 5% through the full swept range with
no wall at all, not just "a wall above 8".

### What this does not yet tell us

- **Not swept past N=5.** A wall could still exist higher up; N=6-8 (the rest of
  doc 2's original range) has not been run. Worth doing before treating this as
  fully bounded, though the monotonic throughput trend argues against an imminent
  cliff.
- **`bad_schema` at N=5 (5/221, 2.3%) is the highest of any arm.** Four data
  points is not enough to call this a trend rather than noise, but it is the
  thing to watch if the sweep is extended -- a rising bad-schema rate with
  concurrency would be a real (if different) capacity signal.
- **Single key, single IP, one session.** This is the ceiling for *this*
  account's *current* load pattern, not a guarantee against Gemini's second
  finding (a slow-accruing penalty from sustained hammering) -- that is what
  experiment 5 (`soak`) is for, and it has not run yet.

## Next steps

1. ~~Resolve the `mistral-large` question directly~~ **Done** -- confirmed 403
   tier-gated, see above.
2. ~~Run `schema` against gate-rung candidates~~ **Done, differently** -- direct
   calls showed there is no usable gate-rung candidate on this account at all
   (see the verified-access table above), which is a stronger answer than the
   `schema` command would have given.
3. ~~Experiment 3 (`concurrency`)~~ **Done. PASS, no wall through N=5.** See above.
4. **Experiment 3b (drafting quality) is now the only remaining decisive
   experiment.** Concurrency and structured-output reliability are both
   confirmed adequate; the sole open question is whether `ministral-8b`/`14b`
   drafts survive the existing Gemini gate at an acceptable rate.
5. Optional, lower priority: extend the sweep to N=6-8, and run `soak` (30 min at
   N=4 or 5) to check for a slow-accruing penalty under sustained load, the way
   Gemini had one.
