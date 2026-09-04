# 6. Provider alternatives

> **Researched 2026-09-04.** What our workload actually demands, why almost every
> free tier fails it, and the one finding that reframes the question.
> **Free-tier limits change constantly — every number here needs re-checking
> against the provider's own console before it is acted on.**

## First, what the workload actually needs

Quantifying this properly is what makes the rest of the page decidable. From
[document 4](04-the-concurrency-ceiling.md) and the pipeline's own numbers:

| Property | Value | Source |
|---|---|---|
| Prompt size per call | **5,000–17,000 tokens** | measured `chars=` in run logs (~6k–13k chars, plus structured-output schema) |
| Calls per accepted card | **~3.4** | draft + gate (difficulty + factual) + verification |
| Target throughput | ~600 cards/hr | roughly Benchmark 9's 676 |
| ⇒ **Required calls/min** | **~34** | 600 × 3.4 / 60 |
| ⇒ **Required TPM** | **~400,000** | 34 × ~12k |
| Concurrency needed | ≥ 4, ideally 8–16 | to keep 34 calls/min moving at 7–17s each |
| Structured output | **mandatory** | every call returns a Pydantic-validated batch |

**~400k TPM is the number that kills almost every free tier.** Even our *current*
degraded 340–450 cards/hr needs ~300k TPM. The only reason Gemini's free tier ever
delivered this is that TPM is metered **per key per model**, so 109 keys multiplied
it — which is precisely the arrangement the next section is about.

## The finding that reframes the question

Two facts, put together:

1. **The limit we hit is keyed to the source IP, is undocumented, and no quota
   accounting can see it** ([document 4](04-the-concurrency-ceiling.md)).
2. **Pooling many free accounts to multiply free-tier quota is prohibited by these
   providers' terms.** Groq's Acceptable Use Policy explicitly forbids using the
   service "beyond published parameters, rate limits, or use limitations, including
   by registering multiple accounts or orchestrating usage between multiple
   organizations". Comparable clauses are standard across the industry, and several
   providers additionally share rate limits at the workspace level so that extra
   keys inside one account create no independent throughput at all.

The most economical explanation of this entire saga is therefore: **the IP-keyed
concurrency shedder is an anti-abuse control, and multi-key free-tier pooling is
exactly the behaviour it exists to detect.** That fits every observation — why 109
keys performed no better than 1, why 12 keys from 12 separate projects returned an
*identical* `retryDelay`, why the penalty accrues under sustained load and decays
at the daily reset, and why the error carries no `quotaId`: there is no quota being
exceeded, so there is nothing to name.

If that reading is right, then **"find another provider with a generous free tier
we can pool keys across" reproduces this saga somewhere else**, with the added risk
of account termination rather than a soft throttle. I could be wrong — the
mechanism is inferred, not confirmed by Google — but it is the reading most
consistent with the evidence, and it is cheap to act as if it were true.

This is a factual constraint on the options, not a judgement about the work so far;
109 keys was a reasonable response to a limit that looked like per-key quota.

## The comparison

Free-tier limits as researched on 2026-09-04. **The token budget is what decides**,
not RPM — a single one of our calls is 5–17k tokens.

| Provider | Free RPM | Free token budget | One call fits? | Verdict |
|---|---|---|---|---|
| **Google Gemini** | 15 (Flash) | per key/model, 1,000–1,500 RPD | yes | Where we are. Pro removed from the free tier April 2026. |
| **Groq** | ~30 | **~12k TPM** (70B), 1,000 RPD | **no** — one prompt exceeds TPM | Cannot make a single call per minute |
| **Cerebras** | **5** | 30k uncached TPM, 1M TPD | marginal | **No permanent free tier** — $5 trial credits, 30-day expiry |
| **Mistral** | undisclosed | **~1B tokens/month** | unknown | Most generous token cap here; limits console-only, positioned as evaluation |
| **NVIDIA NIM** | **40** (200 on request) | ~1,000–5,000 credits | likely | **Best RPM fit**, but credits are finite — a trial, not a tier |
| **SambaNova** | 30 | **200k tokens/day** per model | yes, ~16 calls/day | Reports of the free tier being retired |
| **Alibaba Qwen** | — | 70M tokens, 90 days, Singapore only | yes | **Free developer API removed April 2026** — trial only |
| **Scaleway** | — | 1M tokens, one-time | yes, ~80 calls | One-time trial |
| **Z.ai (GLM)** | ~1/s (Flash) | ~1,000 req/day, TPM unpublished | unknown | Limits not published |
| **Cloudflare Workers AI** | high | 10k neurons/day, shared across models | unlikely | Large models burn the pool fast |
| **GitHub Models** | 15 | 150–1,000/day | unlikely | Low daily ceiling |
| **Cohere** | 10–20 | ~100/day | no | Daily ceiling far too low |
| **OpenRouter** | 20 | 50/day (1,000 with $10 top-up) | varies | An aggregator — useful as a router, not as capacity |

### The order-of-magnitude gap

The table above understates the problem, because RPM is not the binding unit. Put
our daily token demand next to the most generous free budgets:

| | Tokens |
|---|---|
| **Our demand, 8h at ~350 cards/hr** (today's real rate) | **~114,000,000/day** |
| **Our demand, 24h at 600 cards/hr** (the target) | **~590,000,000/day** |
| Mistral — the most generous free tier found | 33,000,000/day (1B/month) |
| Cerebras | 1,000,000/day |
| SambaNova | 200,000/day per model |
| Cloudflare | 10,000 neurons/day |

**Even a modest working day exceeds the single most generous free tier by ~3.5x,
and the target exceeds it by ~18x.** Free tiers are sized for prototyping — a few
million tokens a day. This pipeline is a bulk content factory that wants hundreds
of millions. The gap is three to four orders of magnitude at the low end, and no
combination of the providers above closes it.

This is also the honest answer to "how did Gemini ever work?": TPM is metered per
key per model, so 109 keys multiplied a prototyping-sized budget into a
production-sized one. That is the arrangement the previous section is about.

**Not one of these free tiers supports the workload on a single key.** Groq is the
clearest illustration: 12k TPM is smaller than one of our prompts, so we could not
make a *single* call per minute. NVIDIA NIM has the best request ceiling (40 RPM,
200 on request — enough for our ~34 calls/min) and is the one worth an actual probe,
but its budget is a finite credit grant rather than a recurring allowance. Several
tiers that older comparisons list as permanent have since been withdrawn: Cerebras
is now a 30-day trial, Alibaba's free developer API was removed in April 2026, and
SambaNova's is reportedly being retired.

## "Why not just pool Mistral keys, like we did for Gemini?"

> **Superseded 2026-09-04 by [`docs/mistral-saga/01-api-reference.md`](../mistral-saga/01-api-reference.md).** The arithmetic below rests on the
> published "~1B tokens/month" figure. Mistral's actual console limits are
> **per model**, and the small models carry 30-65x the budget of the newest
> mid-tier ones -- so **one key** sustains ~73 of our calls/min against a need
> of ~34. The multi-account question below is moot. The four *non-arithmetic*
> blockers still stand, and the concurrency one is still unanswered.

The obvious question, and the arithmetic answers it more favourably than expected.

| | Gemini (what we did) | Mistral (the proposal) |
|---|---|---|
| Free budget per account | ~1,500 RPD per key/model | ~1B tokens/month ≈ 33M/day |
| Accounts for 114M tokens/day (8h @ 350 cards/hr) | — | **~4** |
| Accounts for 590M tokens/day (24h @ 600 cards/hr) | — | **~18** |
| RPM cover for ~34 calls/min at a reported ~2 RPM/key | — | ~17 keys |
| **Accounts actually needed** | **109 keys** | **~20** |

So pooling Mistral is not numerically absurd — it is roughly **5x more efficient
per account** than what we ran on Gemini. The blockers are not arithmetic:

1. **We do not know whether Mistral has the same edge shedder.** This is the only
   question that matters and no amount of reading answers it. Gemini's limit was
   IP-keyed, undocumented, and invisible to quota accounting; it cost four weeks to
   find. Mistral may have none, or one at 3 concurrent, or one at 50.
2. **Mistral does not publish its free-tier limits** (console-only) and positions
   the tier as evaluation, not production. That fails requirement #1 in
   [doc 5](05-what-we-learned.md) — you cannot engineer a balancer against a limit
   you cannot read, and an unpublished limit changes without a changelog.
3. **Separate accounts, not separate projects.** Our Gemini keys came from projects
   under Google Cloud. Twenty accounts with twenty email addresses is what ToS
   language names explicitly, and Mistral is a far smaller company than Google.
   Google's response to us was a soft throttle that decays daily; a smaller
   provider's response to twenty correlated accounts is more likely to be
   termination, which takes the keys *and* whatever is mid-run.
4. **Reported training-data opt-in** on the free tier. Unverified, but the prompts
   carry our curriculum design and the outputs are the corpus — the product's actual
   asset. Worth confirming before sending it.

Underneath all four: this would rebuild the core content pipeline on an unpaid
dependency, having just been burned by exactly that, in a year when the free-tier
landscape is visibly contracting (Cerebras → trial, Alibaba → withdrawn April 2026,
SambaNova → reportedly retiring).

**The resolution is to measure before provisioning.** Two or three Mistral accounts
and the same `inflight_sweep.py` probe that found Gemini's 3→4 wall settles it in an
afternoon: if Mistral sheds at 3 as well, the other seventeen accounts are saved. See
[`docs/mistral-saga/`](../mistral-saga/README.md) for the provider reference and the
validation harness built for exactly this.

## The three honest options

### A. Pay Gemini (smallest change by far)

Tier 1 reportedly moves 5–15 RPM to **150–300 RPM** on a single project, and the
[ADR-0002](../adr/0002-langchain-behind-an-interface.md) boundary means this is a
billing change plus deleting most of the key-pool machinery — it is exactly the
"config-only upgrade path" [ADR-0003](../adr/0003-free-tier-first.md) §2 was
written to preserve. It also collapses `LoadBalancer`, key boxes, the ladder's
key dimension, and the wave gate into "one key, sane limits".

**Unknown, and worth testing before committing:** whether paid tier removes the
IP-keyed concurrency shedding, or only the quota limits. Cheap to establish — one
billed key, re-run `inflight_sweep.py`, see whether the 3→4 wall moves. **That
single experiment is the highest-value next step on this page**, because if the
wall is a free-tier anti-abuse control it should disappear entirely, and if it does
not, that is important to know before paying anyone.

Caveat from the research: multiple forum reports describe Tier 1 projects still
being served free-tier quota when Cloud Billing is not correctly linked to the
GCP project behind the key. Verify the linkage rather than assuming the upgrade
took.

### B. Gemini Batch API (fits our shape unusually well)

**50% of standard cost**, ~24h target turnaround (often much quicker), supports
structured output and response schemas, **100 concurrent batch requests**, JSONL
uploads to 2GB. This is a paid path, not free.

Our pipeline is a *background corpus builder*, not an interactive service — nobody
is waiting on a card. The drafting stage is the bulk of the calls and is
embarrassingly parallel within a topic. Submitting drafting as batch jobs would
sidestep the interactive concurrency ceiling entirely and halve the price.

It is a real pipeline change (the LangGraph nodes become submit/poll rather than
await) and 24h latency does not suit the gate's feedback loop, so it is likely a
*hybrid*: batch the drafts, keep the gate interactive.

### C. Local generation (already an ADR, still untested)

[ADR-0008](../adr/0008-local-gpu-generation.md) — an RTX 5070 (12 GB) running
Granite 4.1 8B or Qwen3-8B for structured output, prefix-caching the per-topic RAG
context via SGLang or vLLM. No rate limit, no quota, no ToS question, no IP
shedder. Estimated 5–10k cards/day.

**The decisive experiment has still not been run**: draft ~20 cards locally, push
them through the existing Gemini quality gate, compare the accept rate against
Gemini-drafted cards. That one number decides viability, and it costs an afternoon.
If local drafting passes the gate at a comparable rate, the provider question
largely dissolves — Gemini stays only as the *judge*, which is a low-volume role
its free tier can actually serve.

## Recommendation

Run the two cheap experiments before choosing a provider, in this order:

1. **One billed Gemini key, re-run `inflight_sweep.py`.** Establishes whether the
   concurrency wall is a free-tier control. Answers option A and informs everything
   else. Hours.
2. **Local drafting through the existing gate, ~20 cards.** Answers option C, the
   only option with no external ceiling at all. An afternoon.

Switching to another *free* tier is the option I would not take: none of them fits
a 12k-token call on one key, making them viable only by pooling keys — which is
what this saga suggests we should stop doing.

## Sources

- [Free LLM API in 2026: 13 Options Ranked and Compared — OpenRouter](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/)
- [Cerebras — rate limits](https://inference-docs.cerebras.ai/support/rate-limits)
- [Gemini API — rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemini API — Batch API](https://ai.google.dev/gemini-api/docs/batch-api)
- [Mistral free tier (Price Per Token)](https://pricepertoken.com/endpoints/mistral/free)
- [LLM API rate limits by provider — Requesty](https://www.requesty.ai/blog/rate-limits-for-llm-providers-openai-anthropic-and-deepseek)
- [FreeLLMAPI: 34 free tiers, and the ToS clause nobody quotes](https://artificiallyintimidating.com/p/freellmapi)
- [429 RESOURCE_EXHAUSTED on paid Tier 1 — Google AI Developers Forum](https://discuss.ai.google.dev/t/429-resource-exhausted-on-paid-tier-1-quota-appears-stuck-on-free-tier-limits-despite-active-billing/180368)
- [NVIDIA Build / NIM free tier and limits](https://yangmao.ai/en/providers/nvidia-build/free-tier/)
- [Cloudflare Workers AI — free plan limits](https://costbench.com/software/llm-api-providers/cloudflare-workers-ai/free-plan/)
- [Cloudflare Workers AI — JSON mode](https://developers.cloudflare.com/workers-ai/features/json-mode/)
- [Alibaba Cloud Model Studio — rate limiting](https://www.alibabacloud.com/help/en/model-studio/rate-limit)
- [SambaNova Cloud free plan](https://costbench.com/software/llm-api-providers/sambanova-cloud/free-plan/)
- [Scaleway Generative APIs — rate limits](https://www.scaleway.com/en/docs/generative-apis/reference-content/rate-limits/)
- [Z.AI (GLM) free API — models and limits](https://www.free-llm.com/provider/z-ai)
