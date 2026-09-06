# Generation pipeline v2: authored curricula, Mistral prose, Gemini verdicts

> Design, 2026-09-06. Decided with the owner in this session; the numbers and mechanisms
> below are their calls, not defaults. Architecture context:
> [`authored-curriculum.md`](authored-curriculum.md). Provider split:
> [ADR-0090](../adr/0090-hybrid-gemini-mistral-generation.md).

## What changes, in one picture

```
BEFORE                                  AFTER
──────                                  ─────
user requests topic                     owner authors curriculum   (no model)
      ↓                                       ↓
generate_curriculum  (LLM, ungrounded)  project into Topic/Subtopic (no model)
      ↓                                       ↓
subtopics                               subtopics
      ↓                                       ↓
draft in memory ─── all tiers ───┐      draft ─→ PERSIST AS DRAFT immediately
      ↓                          │            ↓
gate + persist per group ────────┘      gate flips draft → active | rejected
      ↓                                       ↓
Gemini for everything                   Mistral prose · Gemini verdicts
```

Three independent changes, each landing on its own: the curriculum stops being generated,
drafts stop being held in memory, and prose moves to Mistral.

## 1. Drafts persist the moment they exist

Yesterday's run held **~350 drafted cards in container memory** across 40 tiers and lost every
one of them when the run stopped, because gate-and-persist runs per subtopic group *after* all
of that group's tiers finish drafting (`nodes.py:796`). Two hours of throttled calls, 86
surviving cards.

**`CardStatus.DRAFT` already exists** for exactly this — *"a generated card is `draft` until
the quality gate passes it. It never reaches the corpus otherwise"* (`domain/enums.py:35`).
So:

- The writer returns → **write `Card` rows at `status=draft` immediately**, before the gate.
- The gate flips each row to `active` or `rejected` in place.
- A run that dies loses nothing but the calls in flight.

**Why this is safe by construction.** The feed's candidate query already filters on
`status='active'`, and `uq_card_family_id_active` is a *partial* unique index
(`WHERE status = 'active'`), so any number of drafts can coexist in a family without
colliding. A draft is invisible to readers, and no feed code changes.

Two details:

- `content_embedding` and `embedding_model` are `NULL` on a draft and set when the gate
  accepts. The existing check constraint (`(content_embedding IS NULL) = (embedding_model IS
  NULL)`) already permits that pairing, so no migration.
- **Rejected drafts keep their row** at `status=rejected`, *and* `rejected_card` is still
  written (owner's call). The card row holds the full body and provenance as an audit trail;
  `rejected_card` keeps carrying the structured reason that feeds prevention context back
  into the next `generate_cards` call. Neither loop changes.

Orphan drafts from a killed run are a real state and an honest one: they are visible, they
are not served, and a later pass can gate or discard them.

## 2. Mistral writes prose, Gemini judges

Per ADR-0090, unchanged: **verdicts on the thinker, prose on the generator.**

| Role | Calls | Provider |
|---|---|---|
| Generator | `plan_cards`, `fetch_ascii_scenes`, `generate_cards`, `correct_cards`, `generate_questions`, `repair_card_structure`, `stream_topic_answer` | **Mistral** |
| Thinker | `verify_cards`, `grade_free_text`, `validate_topic_names`, `match_topics` | **Gemini** |

`generate_curriculum` leaves the table entirely — it is deleted, not reassigned.

### Configuration, as decided

| Setting | Value | Why |
|---|---|---|
| Model | **`ministral-8b`** | Measured real post-RAG prompts: p50 ~12.5k chars (~3.1k tokens), max 23.6k (~5.9k). 8b only drops below target rate above ~18k tokens, so there is real headroom, including for ADR-0099's taller scenes |
| Keys | **1 now**, multi-key capable | The client takes a list and round-robins; the list currently has one entry |
| In-flight cap | **5** | The concurrency sweep's proven ceiling with no wall |
| Transport | raw `httpx`, `POST /v1/chat/completions` | ADR-0090; avoids a new LangChain dependency and a new banned-api entry |
| Structured output | `response_format: {type: json_schema, strict: true}` | Proven by the probe across 646 calls at 12k tokens |
| Parsing | existing `_LenientWireModel` Pydantic models | No second parsing path |

**What is deliberately *not* built:** no key pool, no box leasing, no quota ledger, no load
balancer, no send-gap pacing, no rung ladder. ADR-0090 warns explicitly against porting the
Gemini apparatus to a provider that does not have Gemini's problem. Mistral gets a semaphore,
a send path, and retry.

The Gemini machinery stays exactly as it is — the thinkers still run on it, and ADR-0084's
LoadBalancer is still what schedules them.

## 3. Going in blind: log everything

We do not know Mistral's failure shape, its error codes, or whether the sweep transfers to
real prompts. So the client captures everything and we decide what matters afterwards
(owner's call).

**Per-run JSONL**, one line per call, written to a file rather than stdout so it does not
drown the pipeline log:

```json
{"ts": "...", "call": "generate_cards", "attempt": 1, "key_index": 0,
 "model": "ministral-8b", "status": 200, "latency_s": 3.4,
 "in_flight_at_send": 4, "prompt_chars": 12465, "prompt_tokens_est": 3116,
 "usage": {...}, "request_id": "...", "headers": {...}, "body": {...}}
```

Everything: status code, **all response headers** (rate-limit headers are how we learn its
limits without documentation), latency, in-flight count at send time, prompt size, reported
usage, request id, and **the full response body on success as well as failure** (owner's
call — the complete record of what the model actually returned, which is what diagnoses
malformed structured output).

The one thing that stays in the main log is a summary line per call, matching the existing
`lbprobe call` shape so a terminal remains readable.

**Classification is deliberately absent at first.** We do not pretend to know which status
codes mean what. Retry on anything retryable-looking with backoff; record everything; derive
the taxonomy from the first real runs. This is the discipline the mistral-saga exists to
enforce: measure a provider's behaviour before building on it.

### Failure handling

- Retry with backoff on transient-looking failures.
- If it still fails, **that item fails and the run continues** — counted as a *call failure*,
  never as a rejection. CLAUDE.md is specific that folding those together makes a
  provider outage read as a content-quality catastrophe.
- **No cross-provider fallback.** A Mistral outage stays visible as a Mistral outage rather
  than silently becoming a Gemini bill and a corpus you cannot attribute afterwards.

## 4. The run

```bash
python -m spoin.generate_topics "Rust"
```

A CLI over an **authored** topic, run locally (ADR-0094: generation is local and manual, no
cron refill). It no longer takes a description or mints a topic — the topic exists because a
curriculum was projected. One process, one log stream, one JSONL file, easy to stop.

The worker path is not deleted, but nothing routes to it until curricula exist for whatever
users request.

## 5. What does not change

- **No LLM in the feed read path** (hard rule 1), and the feed only ever sees `active` cards.
- **Card grounding** — top 2, no floor, no token budget (ADR-0089 as amended).
- **The two-pass gate**, dedup, ASCII fetch, question generation, the quiz ladder.
- **Every LLM interface method takes a collection** (ADR-0005), Mistral's included.
- **LangChain/LangGraph confinement** (ADR-0002) — and Mistral on raw httpx adds no new
  import to confine.
- **`spoin` imports `frog`, never the reverse.**

## 6. Build order

| # | Task | Depends on |
|---|---|---|
| 1 | Curriculum contract + `make curriculum-check` (pure validation) | — |
| 2 | Curriculum tables in `the_spoin_universe` + ingestion, own alembic revision | 1 |
| 3 | Projection into `Topic` / `Subtopic` (plain upsert, no model) | 2 |
| 4 | Author Rust's curriculum end to end and project it | 1–3 |
| 5 | Persist drafts immediately; gate flips status in place | — |
| 6 | `MistralContentGenerator`: httpx client, semaphore at 5, JSONL logging | — |
| 7 | `HybridContentGenerator` routing per ADR-0090's table | 6 |
| 8 | Delete `generate_curriculum` and its prompts; rewire `resolve_and_plan_topic` | 4 |
| 9 | CLI over an authored topic | 3, 8 |
| 10 | Run Rust end to end; read the JSONL; write up what Mistral actually does | 4–9 |
| 11 | ADRs from what 10 showed — including whether 5 in flight was right | 10 |

**5 and 6 are independent of 1–4** and can land first, which is useful: persisting drafts
immediately makes every subsequent experiment cheaper to lose.

Task 4 before task 8 on purpose — prove the authored path on a real topic before deleting the
generated one.

## The open question task 10 answers

Whether `ministral-8b` at 5 in flight actually sustains the pipeline on real RAG prompts. The
sweep that produced "no wall through N=5" ran on synthetic 12k-token filler, and a real
grounded prompt has different structure and different token accounting. The JSONL is what
turns that from an assumption into a measurement.
