# ADR-0085: Meter tokens per minute, not just requests

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** project owner, agent session

## Context

[ADR-0005](0005-batch-llm-calls.md) established that every LLM-facing interface
method takes a collection, and `config.py` justified the batch sizes with a
sentence that turned out to be false:

> The free tier meters requests, not tokens.

Tokens are metered too — free tier is **250,000 TPM per project per model**
across the flash and flash-lite families. Nothing in the codebase knew that. The
ladder config carried `rpd` and `rpm` and no token dimension at all, so the
balancer could pace a cell perfectly by request count while sending it an
unbounded number of tokens.

The premise mattered because it pointed the batch sizes the wrong way. If only
requests are metered, a bigger batch is free throughput, so
`verification_batch_size` grew to 40 and the ASCII fetcher retrieved
`k=10` candidate artworks *per card* and concatenated them into one prompt —
an N-ascii-card tier sent N x 10 full artworks in a single request. Measured
against the live library that is ~3,172 chars of art per query, so a 10-card
tier produced a ~32k-char prompt, which matched the largest prompt observed in
a real run (32,287 chars) almost exactly.

Four benchmarks of the ADR-0084 load balancer failed in the same 84-95% 429
band regardless of key count (34 vs 75) or send pacing (15/min vs 6/min per
cell), and the pipeline's 429s carried no `quotaId` at all — the bare
`RESOURCE_EXHAUSTED` envelope, which names no quota to attribute against.
Investigation ruled out shared projects, account flagging, per-day exhaustion,
per-IP limiting, the SDK, and our own pacing (measured true per-cell send
spacing was p50 49.5s). See
[the benchmark writeup](../handoff/adr-0084-send-gap-benchmarks.md) for the
full evidence trail, including the theories that were disproved.

## Decision

Tokens per minute become a first-class limit alongside requests per minute.

- `LadderRung` gains **`tpm`**, defaulting to 250,000. `parse_ladder` accepts
  `model:rpd:rpm` and `model:rpd:rpm:tpm`, so existing ladder strings parse
  unchanged.
- `_CellState` gains a **`token_window`** — `(sent_at, tokens)` per send,
  pruned on the same trailing 60s cutoff as the request `window`. Unlike the
  request window it is **never dormant under pacing**: a constant send gap
  bounds requests per minute and says nothing about tokens, and a batch call's
  token cost varies by orders of magnitude.
- `try_assign` skips a cell whose windowed tokens plus this call's estimate
  would exceed the rung's `tpm`, and reports the time until enough tokens age
  out — the same shape as every other reason it declines a cell.
- Token cost is estimated **before** the send as `len(prompt) // 4`, and
  recorded in `note_send` anchored to the true send time. `on_send_aborted`
  refunds the token slot, as it already did the request slot.
- The two biggest token consumers are cut on the same reasoning:
  `verification_batch_size` 40 -> 20 (each verified card carries its body and
  its ascii art into the prompt) and the fetcher's `_ASCII_CANDIDATE_COUNT`
  10 -> 5 (it multiplies per query).

## Consequences

**A cell can now be declined for a reason the provider never tells us.** Our
429s carry no `quotaId`, so a TPM rejection is indistinguishable from an RPM one
in the error. The token ceiling is therefore enforced entirely from our own
accounting — it is a brake we apply, not a limit we detect. If the real TPM is
higher than configured we throttle ourselves for nothing; if lower, we still
429. The number is owner-supplied from the provider's published figure, the
same provenance as `rpd`/`rpm`.

**The estimate is an estimate.** `chars // 4` is the usual English rule of
thumb, good to roughly ±20%. The exact figure is only knowable from the
response's `usageMetadata`, which `with_structured_output` does not surface (it
returns the parsed model, not the `AIMessage`); reconciling against the real
count needs `include_raw=True` and a change to every call site's return shape,
so it is deferred to a task rather than done here. A brake sized on a ±20%
estimate still brakes.

**Per-cell TPM may rarely bind on its own.** At `rpm=15` and the largest prompt
measured (~8k tokens), one cell tops out near 120k tokens/min — under the 250k
ceiling. The window's near-term value is the per-cell token accounting we have
never had; the batch cuts are what actually reduce volume today. This is stated
plainly because it is the most likely way this ADR turns out to be wrong.

**ADR-0005's rule stands; its stated reason does not.** Batching is still
correct — one 15-card call beats 15 single-card calls on both requests and
tokens — but a batch size now trades requests against tokens rather than buying
throughput for free. `config.py`'s comment is corrected in the same change.

## Alternatives considered

**Leave batch sizes alone and rely only on the token window.** Rejected: the
window declines a cell, it does not shrink the call. A single 32k-char fetcher
prompt is unchanged by any amount of pacing, so the sizes that produced it had
to move too.

**Call `count_tokens` before each send for an exact figure.** Rejected: it is
an additional API request per call against the same metered pool — paying a
request to learn about tokens, on a tier where both are scarce.

**Cap total tokens in flight globally instead of per cell.** Rejected for now
as a bigger change to the balancer's contract (it owns cells, not a global
semaphore), and because the evidence that the limit is aggregate rather than
per-project is not conclusive — see "Revisit when".

## Revisit when

- A run paced by this window still shows bare 429s at low per-cell token rates.
  That would mean the ceiling is **aggregate across keys**, not per project per
  model, and the fix is a global token semaphore rather than a per-cell window.
- The deferred `usageMetadata` reconciliation lands and shows the `chars // 4`
  estimate is off by enough to matter.
- Google publishes different TPM figures, or the ladder gains a paid tier.
