# 1. Mistral API reference

> **Compiled 2026-09-04.** Model IDs and prices from Mistral's docs and provider
> references; **the rate limits are real numbers read off the account's
> Organization Limits console**, which is the only trustworthy source — Mistral
> does not publish per-tier limits. Start at
> [Limits](#limits--measured-from-the-console-2026-09-04): it is the section that
> decides the integration, and it inverts the obvious model choice.

## Endpoint and shape

| | |
|---|---|
| Base URL | `https://api.mistral.ai/v1` |
| Chat endpoint | `POST /v1/chat/completions` |
| Model discovery | `GET /v1/models` |
| Auth | `Authorization: Bearer <key>` |
| Request shape | OpenAI-compatible (`model`, `messages`, `max_tokens`, `temperature`, `response_format`) |

The OpenAI-shaped request body is the single most important integration fact:
it means the probe needs no SDK, and a future `MistralContentGenerator` can be a
thin implementation rather than a new dependency graph. `langchain-mistralai`
exists if we want `with_structured_output` parity with the Gemini path, but it is
**not currently a dependency** and adding it would need an
[ADR-0002](../adr/0002-langchain-behind-an-interface.md) `banned-api` entry
alongside the existing ones.

## Models

Model IDs and context windows as of 2026-09-04. `-latest` aliases float; pin a
dated snapshot for anything reproducible.

| Model ID | Context | Notes |
|---|---|---|
| `mistral-medium-latest` | 256k | Mistral Medium 3.5 — frontier-class, multimodal, agentic/coding focus. Sits first in Mistral's own list and costs ~3x input / ~5x output vs Large 3 |
| `mistral-large-latest` | 256k | Mistral Large 3 — open-weight, general-purpose multimodal. **$0.50/1M in, $1.50/1M out** |
| `mistral-small-latest` | 256k | Mistral Small 4 — hybrid instruct + reasoning + coding, `mistral-small-2603`. **$0.15/1M in, $0.60/1M out** |
| `magistral-medium-latest` | 128k | Reasoning model, tokenized thinking chunks (currently the 2509 generation) |
| `ministral-14b-latest` | 256k | Efficiency tier |
| `ministral-8b-latest` | 256k | Efficiency tier |
| `ministral-3b-latest` | 128k | Smallest |
| `codestral-latest` | 256k | Code. **$0.30/1M in, $0.90/1M out** |
| `devstral-medium-latest` | 256k | Agentic coding |
| `open-mistral-nemo` | 128k | Open weights |
| `mistral-embed` | 8k | Embeddings — **not needed**, we embed locally |

**Do not map these onto our ladder by capability.** The obvious reading of this
table — Small for bulk drafting, Medium/Magistral for the gate — is precisely
backwards once the rate limits below are applied: those three models have the
tightest budgets on the account. The ladder proposal lives in
[Limits](#what-this-does-to-the-plan) instead, derived from capacity first and
sanity-checked for capability second.

The 256k context is still a genuine advantage over what we use today: our largest
batches are ~17k tokens, leaving enormous headroom for
[ADR-0085](../adr/0085-tokens-are-metered-too.md)-style packing — and packing is
worth more here than it was on Gemini, because a per-model TPM budget rewards
fewer, larger calls directly.

## Structured output

Two mechanisms, and the distinction matters:

| Mode | `response_format` | Reliability |
|---|---|---|
| **Custom structured output** | `{"type": "json_schema", "json_schema": {"name": ..., "schema": {...}, "strict": true}}` | Mistral's docs recommend this "whenever possible" |
| **JSON mode** | `{"type": "json_object"}` | Requires explicit format instructions in the prompt |

We need the first. The probe's `schema` command exercises it with a card-batch
schema at pipeline prompt weight, because the docs still advise iterating on
prompts even with structured output — which is a soft admission that schema
adherence is not guaranteed, and
[CLAUDE.md](../../CLAUDE.md)'s "trusted for taste, never for constraints" rule says
we verify rather than assume.

**A 200 carrying unparseable JSON is tracked as a distinct outcome (`bad_schema`)
in the harness**, never folded into a generic failure rate. It is a completely
different problem from a throttle: no amount of pacing fixes a model that cannot
hold our schema.

## Limits — SUPERSEDED, see doc 3

> **The table originally here was wrong and has been removed.** It was read off
> the Organization Limits console, which turned out to list rate limits for
> models this account is 403'd on ("tier-gated") and does not distinguish a
> real per-model budget from a permanent zero allocation. **Never trust that
> console page over a real call again** -- verify with
> [doc 3's findings](03-findings.md#resolved--the-real-verified-model-access-for-this-key-2026-09-04),
> which tested every plausible model directly and reads the
> `x-ratelimit-limit-*` response headers rather than the console.

### The verified reality (2026-09-04, this key)

| Access | Models | TPM | RPM |
|---|---|---:|---:|
| **Usable** | `ministral-3b`, `ministral-8b`, `ministral-14b`, `codestral` | 625k–1.3M | 30–750 |
| **403 tier-gated** | `mistral-large`, `labs-leanstral` | — | — |
| **429, limit=0 (permanent)** | `mistral-small`, `mistral-medium`, `magistral-small`, `magistral-medium`, `mistral-vibe-cli` | — | 0 |

**This account has no reasoning-capable model at any usable rate.** Every model
with real budget is a small, fast completion model (3B–14B). There is no gate-rung
candidate on this tier — `mistral-medium` and `magistral-medium`, the two obvious
judge candidates, are both permanently rate-limited to zero.

### What this does to the integration shape

The ladder concept from [ADR-0028](../adr/0028-key-model-quota-ladder.md) —
draft on a fast model, judge on a strong one, both from the same provider — **does
not fit this tier.** The only viable shape is the one
[doc 2's experiment 3b](02-validation-plan.md#experiment-3b--drafting-quality-on-the-small-models--new-and-now-co-decisive)
already proposed for a different reason (isolating drafting quality from judging
quality): **Mistral drafts, the existing Gemini gate judges.** That is not a
methodology choice any more — it is the only configuration this tier supports.

Two consequences worth stating:

1. If this is genuinely a permanent free/experiment-tier restriction (not
   something this specific account can appeal), **every Mistral account created
   for pooling would have the same restriction** — so the multi-account pooling
   question is not just de-prioritized (as the earlier revision of this page
   said) but may not have a materially different answer no matter how many
   accounts exist, unless a paid tier lifts it.
2. This makes [experiment 3b](02-validation-plan.md) (drafting quality through the
   Gemini gate) the load-bearing experiment for the whole evaluation, not one of
   several. If Ministral drafts do not hold up under Gemini's gate, there is
   currently no path to a self-contained Mistral pipeline on this account.

## Sources

- [Mistral Docs — models overview](https://docs.mistral.ai/getting-started/models/models_overview/)
- [Mistral Docs — custom structured output](https://docs.mistral.ai/capabilities/structured-output/custom_structured_output/)
- [Promptfoo — Mistral provider reference](https://www.promptfoo.dev/docs/providers/mistral/) (model IDs, context windows, pricing, base URL)
- [Mistral free tier (Price Per Token)](https://pricepertoken.com/endpoints/mistral/free)
- [Mastra — Mistral model IDs and pricing](https://mastra.ai/models/providers/mistral)
