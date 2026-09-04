# ADR-0090: One `HybridContentGenerator` routes generator-ladder calls to Mistral over raw `httpx` and keeps thinking-ladder calls on Gemini

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** project owner, implementing session

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

**`HybridContentGenerator` implements the existing `ContentGenerator` ABC and routes
by the ladder a call already belongs to: generator-ladder calls go to Mistral,
thinking-ladder calls stay on Gemini.**

### The routing table, verified against the code

Task 0038's draft table said to "confirm each method's real ladder against the code
before trusting this table." Confirmed against `langchain_impl.py`'s
`_invoke_with_retry` call sites — **and the draft was wrong in one place and
incomplete in two.**

| Method | Ladder in code | Routes to |
|---|---|---|
| `plan_cards` | generator | **Mistral** |
| `fetch_ascii_scenes` (and the ASCII redraw call) | generator | **Mistral** |
| `generate_cards` | generator | **Mistral** |
| `generate_questions` | generator | **Mistral** |
| `repair_card_structure` | generator | **Mistral** |
| `stream_topic_answer` | generator | **Mistral** |
| `generate_curriculum` | thinking | **Gemini** |
| `match_topics` | thinking | **Gemini** |
| `validate_topic_names` | thinking | **Gemini** |
| `correct_cards` | thinking | **Gemini** |
| `verify_cards` | thinking | **Gemini** |
| `grade_free_text` | thinking | **Gemini** |
| `claimed_key_scope`, `lease_key_box`, `release_key_box` | — | **Gemini** (box leasing is Gemini-pool-specific) |

Three corrections to the draft:

1. **`correct_cards` is a thinking call, not a generator call.** The draft put it on
   Mistral. It is one half of [ADR-0030](0030-two-pass-quality-gate.md)'s two-pass
   quality gate — judgment, not drafting — and moving it to a 3B model would put the
   gate's correction pass on a weaker model than the thing it is correcting.
2. **`stream_topic_answer` was missing.** AskAI ([ADR-0077](0077-askai-deterministic-single-call-retrieval.md))
   runs on the generator ladder and therefore moves to Mistral.
3. **`match_topics` was missing.** Thinking ladder, stays on Gemini.

Routing by existing ladder rather than by a new hand-written list is deliberate: the
ladder split ([ADR-0028](0028-key-model-quota-ladder.md),
[ADR-0029](0029-questions-join-generator-pool.md)) already encodes CLAUDE.md's
"trusted for taste, never for constraints" judgment about which calls have a real
consequence when a weak model answers them. Re-deriving that split by hand would be re-litigating a decision
that already has reasoning behind it.

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
- The account's tier changes and a reasoning-capable Mistral model becomes callable.
  The hybrid exists *because* one does not.
