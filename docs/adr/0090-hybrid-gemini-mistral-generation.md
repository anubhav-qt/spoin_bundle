# ADR-0090: One `HybridContentGenerator` routes generator-ladder calls to Mistral over raw `httpx` and keeps thinking-ladder calls on Gemini

- **Status:** Accepted, then **partly superseded** by
  [ADR-0103](0103-mistral-runs-the-thinkers-too.md) (2026-09-07)
- **Date:** 2026-09-04
- **Deciders:** project owner, implementing session

> ⚠️ **The routing table below is no longer what runs.** ADR-0103 moved the thinking
> ladder to Mistral too (`ministral-14b-2512`) and deleted `mistral_max_in_flight`.
> Only a prompt carrying a non-text part still goes to Gemini. What remains live in
> this ADR is its *reasoning* — the measurements, why a hybrid was right at the time,
> and the no-cross-provider-fallback rule, which is unchanged. Read ADR-0103 before
> trusting any routing claim here.

## Context

The [gemini-saga](../gemini-saga/README.md) ended at an undocumented, IP-keyed
**concurrency** ceiling: requests from this source IP simultaneously awaiting a
response shed with a hard wall between 3 and 4, shared across every key in the pool.
Adding keys bought nothing. Four weeks went into discovering a limit that was invisible
to quota accounting.

The [mistral-saga](../mistral-saga/README.md) measured Mistral before building on it —
the one rule that saga cost bought. Results:

- **No concurrency wall through N=5. Zero 429s in 641 calls.** Throughput rises with
  concurrency. The opposite of Gemini's behaviour.
- **Structured output is reliable at 12k tokens** — 646 calls, isolated `bad_schema`
  only, over OpenAI-compatible `POST /v1/chat/completions` with
  `response_format: {type: json_schema, strict: true}`.
- **This account can only call `ministral-3b/8b/14b` and `codestral`.** Everything
  Small/Medium/Magistral returns 429 with `x-ratelimit-limit-req-minute: 0` — a
  permanent zero allocation, not a transient throttle. `mistral-large` and
  `labs-leanstral` are 403 tier-gated. **There is no reasoning-capable Mistral model
  on this tier at all.**

That last point is what forces a hybrid rather than a migration. Mistral has the
throughput Gemini lacks; Gemini has the reasoning Mistral cannot offer here.

## Decision

**`HybridContentGenerator` implements the existing `ContentGenerator` ABC. The split
is by what a call PRODUCES: a call that produces a verdict runs on Gemini's thinking
cells; a call that produces prose runs on Mistral.**

### The routing table

Task 0038's draft table said to "confirm each method's real ladder against the code
before trusting this table." Confirmed against `langchain_impl.py`'s
`_invoke_with_retry` call sites — which turned up two methods the draft omitted
entirely, and one whose placement is a real decision rather than a lookup.

| Method | Produces | Routes to |
|---|---|---|
| `plan_cards` | a plan | **Mistral** |
| `fetch_ascii_scenes` (and the ASCII redraw call) | a scene + caption | **Mistral** |
| `generate_cards` | prose | **Mistral** |
| `correct_cards` | rewritten prose | **Mistral** |
| `generate_questions` | prose | **Mistral** |
| `repair_card_structure` | repaired prose | **Mistral** |
| `stream_topic_answer` | prose | **Gemini** (flash-lite) — see below |
| `generate_curriculum` | structure + judgment | **Gemini** |
| `match_topics` | a verdict | **Gemini** |
| `validate_topic_names` | a verdict | **Gemini** |
| `verify_cards` | **a verdict** | **Gemini** |
| `grade_free_text` | a verdict | **Gemini** |
| `claimed_key_scope`, `lease_key_box`, `release_key_box` | — | **Gemini** (box leasing is Gemini-pool-specific) |

Two methods the draft omitted: **`stream_topic_answer`** (AskAI,
[ADR-0077](0077-askai-deterministic-single-call-retrieval.md)) and **`match_topics`**.

**AskAI stays on Gemini's flash-lite generator ladder** rather than moving to Mistral
with the rest of the prose calls (owner's decision, 2026-09-05). It produces prose, so
the rule above would put it on Mistral — but it is the one *user-facing, latency-visible*
call in the table, and it is low-volume compared to card generation. Keeping it on
Gemini reserves Mistral's throughput entirely for the batch work that needs it. This is
a capacity-allocation exception to the verdict/prose rule, not a revision of it; it will
still be grounded in frog like everything else.

#### `correct_cards` moves to the generator side, and `verify_cards` never does

This is the load-bearing line, and it is a **change to the ladder the code uses
today**: `correct_cards` currently runs on the thinking ladder as one half of
[ADR-0030](0030-two-pass-quality-gate.md)'s two-pass gate. It moves to the generator
ladder, on both providers.

The two halves of that gate do genuinely different work, and treating the pass as one
unit had been hiding it:

- **`verify_cards` decides.** It returns accept/reject. That is a *constraint*, and
  CLAUDE.md's rule is that constraints are never trusted to the cheap path. It stays
  on the thinking cells permanently — not "for now", not "until Mistral improves".
- **`correct_cards` rewrites.** It takes a card and a criticism and produces better
  prose. That is *taste*, and taste is what the generator ladder is for.

What makes the move safe rather than a corner cut is
[ADR-0089](0089-retrieval-grounded-generation.md): correction happens **against a
retrieved source**, so the rewriting model is not being asked to recall a fact — it is
being asked to restate one it has been handed. Recall is the capability a 3B model
lacks and a frontier model was quietly compensating for; restatement is not. And the
verdict that follows is still Gemini's, so a bad correction is caught rather than
shipped.

This applies from the first pass, not only after a redraft round. If the corpus turns
out thin, this is the first decision to revisit — see "Revisit when".

**Applied to the Gemini path on 2026-09-05**, ahead of frog being wired in — the
owner's call, made knowing the retrieval premise is not yet live. Until the corpus
exists, `correct_cards` is running ungrounded on the lite ladder, which is the weaker
of the two conditions the decision was argued from. The revisit condition below is the
thing that catches it if that turns out to be a bad trade.

#### Why route by what a call produces

The routing rule and the ladder split ([ADR-0028](0028-key-model-quota-ladder.md),
[ADR-0029](0029-questions-join-generator-pool.md)) stay the same object, so there is
one list rather than two that drift. Both now say the same thing in the same words:
**verdict on the thinker, prose on the generator** — CLAUDE.md's "trusted for taste,
never for constraints", applied per call rather than per pass.

### Raw `httpx`, not `langchain-mistralai`

The probe already proved the exact request shape works at 12k tokens across 646 calls.
Raw `httpx` avoids a new LangChain dependency and a new
[ADR-0002](0002-langchain-behind-an-interface.md) `banned-api` entry. Responses parse into the
existing `_LenientWireModel` Pydantic models, so the wire/domain split is unchanged.

### Most of the Gemini machinery is not ported

**No key pool, no box leasing, no quota ledger, no load balancer for the Mistral side.**
Mistral needs one key, a send path, structured-output parsing, a modest in-flight cap,
and retry on 429/503.

ADR-0082/0083/0084/0086 — fixed key boxes, least-spent balancing, the per-box load
balancer, dispatch stagger and jitter — are all machinery built to survive a
concurrency ceiling that **Mistral was measured not to have**. Porting them would be
carrying four weeks of scar tissue onto a provider without the wound. If Mistral later
turns out to shed under load, the soak test is what finds it and this decision reopens.

### Failure counts stay three-way

Per CLAUDE.md and the pipeline's existing `_process_gate_item` fix: `bad_schema`,
gate rejection, and call failure are **three separate counts**. A call that never
returned a verdict is not the same fact as content that was judged and found bad. A
new provider is exactly the condition under which conflating them would misread a
transport problem as a quality catastrophe.

## Consequences

**Easier.** Drafting throughput stops being governed by an IP concurrency wall.
Generator-ladder volume comes off Gemini's budget entirely, which makes the thinking
ladder's much smaller daily budget go further. Provider risk is split: an outage at
either provider degrades half the pipeline rather than all of it.

**Harder.** Two providers means two failure vocabularies, two retry policies, and two
sets of rate-limit semantics to keep straight in logs. A drafting model that is much
weaker at instruction-following makes every instruction-only rule more fragile —
[task 0038](../tasks/0038-frog-rag-and-hybrid-generation.md)'s ASCII box rule is the
known live example, and it is deliberately left open for its own decision rather than
settled here. Raw `httpx` means we own the retry, timeout and parse code that LangChain
would have supplied.

**Committed to.** Gemini remains a hard dependency for judgment calls. This is not a
migration away from Gemini and should not be described as one.

## Alternatives considered

**Move everything to Mistral.** Simplest operationally, one provider. Impossible on
this tier: every reasoning-capable model returns a permanent zero rate limit or a 403.
The gate would run on `ministral-3b`, judging drafts written by `ministral-3b`.

**Stay entirely on Gemini.** No new provider, no hybrid complexity. Rejected: the
concurrency ceiling is the binding constraint on throughput and no amount of key-pool
engineering moved it — that conclusion is what the whole gemini-saga documents.

**`langchain-mistralai`.** Consistent with how Gemini is called, retries supplied.
Rejected: a new LangChain dependency and a new ADR-0002 boundary entry, to wrap a
request shape a committed probe has already exercised 646 times.

**Port the load balancer to Mistral.** Defensible on "it already exists". Rejected:
it solves a measured-absent problem, and the cost of carrying it is that a future
reader cannot tell which parts of it are load-bearing.

**Route by hand-written method list instead of by ladder.** Rejected: the ladder split
already carries the reasoning, and a second list would drift from it.

## Revisit when

- The soak test (30 minutes at the chosen concurrency) shows a slow-accruing penalty.
  Gemini's ceiling was invisible to short runs; if Mistral has one, this is what finds
  it, and the "no load balancer" decision reopens immediately.
- Phase 6's accept-rate comparison lands below the fixed thresholds: within ~10 points
  of the Gemini baseline passes; 10–25 points below is marginal and points at
  `ministral-14b` or restricting Mistral to the ASCII-fetch sub-task; more than 25
  points below fails and this ADR is superseded.
- **Corrected cards start failing verification more often than uncorrected ones.**
  That is the signal that moving `correct_cards` to the generator side outran the
  corpus, and the response is to move it back rather than to argue with the numbers.
  Phase 6 measures it for free — it already counts gate rejections separately from
  call failures.
- Someone proposes moving `verify_cards` to the generator side. It does not move.
  That is the one row in the table that is a rule rather than a placement.
- The account's tier changes and a reasoning-capable Mistral model becomes callable.
  The hybrid exists *because* one does not.
