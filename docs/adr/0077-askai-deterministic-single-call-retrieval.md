# ADR-0077: AskAI — deterministic single-call retrieval, streamed, with an embedding-gated scope

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Anubhav

## Context

The card action row has an "Ask AI" button (`Card.tsx`) that records an
`ask_ai` engagement event and otherwise does nothing. B12/B13 on the finish-line
plan is to make it answer a reader's question about the card.

The plan worked through the shape at length and settled it:

- **Not an MCP server over the database.** MCP exists so an *external* agent can
  discover tools; here the caller is our own backend with the SQLAlchemy models
  already loaded. A DB-access tool driven by user text, on a path that returns to
  the user, is a prompt-injection target with a data-exfiltration payoff. And a
  tool-calling loop is 3–6 requests per question, which is the opposite of
  ADR-0005's "the free tier meters requests" premise.
- **Deterministic retrieval, one call.** The server assembles the context itself
  with one query, makes a single flash-lite call through the existing quota
  governor, and returns the answer. Off-topic questions are held out by four
  layers, cheapest first: structural context-scoping, a hard system prompt, a
  free local-embedding pre-check, and a self-declared scope verdict.

Two later decisions refine that:

- **No quota partitioning (plan commit `d0b2a7b`).** Earlier plan text gave
  generation a reserved floor and tagged each request's consumer. That was
  deleted. 33 keys × 2 flash-lite models × 500/day ≈ 33k requests/day is ample
  for both, so AskAI and the pipeline draw from the **same** ladder with no
  reservation, no floor, and no consumer tag. The only limit is **200 questions
  per user per day**.
- **Streamed, with the embedding gate (owner, this session).** The answer streams
  token by token. That collides with a structured `{on_topic, answer}` verdict —
  you cannot stream a boolean-gated string — so the reconciliation below keeps it
  to one request.

## Decision

### The endpoint

**`POST /cards/{card_id}/ask`**, body `{ "question": str }`, responds
`text/event-stream` (Server-Sent Events). This is the **first streaming endpoint
in the codebase** — everything else is request/response.

SSE event types:

| event | payload | meaning |
|---|---|---|
| `delta` | `{text}` | a chunk of the answer |
| `done` | `{}` | answer complete |
| `off_topic` | `{hint}` | the question isn't answerable from this card; `hint` points at what this card *does* cover |
| `limit` | `{}` | the caller hit 200 questions today |
| `error` | `{cause}` | the call couldn't be placed — `cause` is the ADR-0065 distinction (daily-exhausted / all-throttled / models-parked), never folded into "off_topic" |

### Per-user daily cap

New table **`ask_usage`** — `(day, user_id, questions_spent)`, PK `(day,
user_id)`. A plain counter, **not** the quota governor: the governor rations a
shared provider budget, this rations one user against everyone else.
`Settings.ask_ai_daily_limit` defaults to 200. `day` is the **UTC** day (matches
`quota_ledger`'s `_day_start`; ADR-0062's "reader's local day" is a
goal-ring display choice, not a rate-limit boundary).

Over the limit → the stream opens, emits one `limit` event, closes. A clear
"you've reached today's limit" state in the UI, never a bare HTTP 429.

Only a call that actually reaches the provider increments `questions_spent` — a
cache hit, an embedding-gate refusal, and an `error` all cost nothing and count
nothing.

### Cache

**`card_qa`** — `(id, card_id, question_norm, answer, on_topic, created_at)`,
unique `(card_id, question_norm)`. `question_norm` normalises like
`normalize_topic_text` (lowercase, collapse whitespace and punctuation). A hit
replays the stored `answer` as `delta` chunks so the client path is identical,
with no LLM call and no cap increment. `on_topic=false` rows are cached too — a
repeated off-topic question shouldn't cost a call to re-refuse.

### Retrieval — deterministic, one query, tightly scoped

The server builds the context: the card; its subtopic and topic (with
descriptions); sibling subtopics in the same topic; the same `subtopic_group_id`
at adjacent difficulties; and the top-k nearest cards by `content_embedding`
within the topic. **No search tool, no browser, no other users' rows, no rest of
the corpus.** This structural scoping (plan layer 1) is the single biggest reason
there is no general DB tool behind this endpoint: most off-topic questions have
nothing in context to answer from and fail here for free.

### The off-topic gate, in one request

1. **Embedding pre-check — free, no LLM.** Embed the question with the local
   embedder; take the max cosine similarity against the card, subtopic, and topic
   embeddings. Below `Settings.ask_ai_topic_similarity_floor` → emit `off_topic`,
   close. No call, no cap increment. The floor is a calibrated threshold shipped
   with a conservative default and a calibration task (like ADR-0001 for topic
   matching) — with the `HashEmbedder` stand-in the check is meaningless and is
   skipped, exactly as the accent-colour and ASCII features already handle a
   non-real embedder.

2. **One streamed flash-lite call** through the `_generator` `QuotaGovernor` pool
   and ladder — the same pool card generation uses (no reservation, per
   `d0b2a7b`). The system prompt names the card's title and topic and instructs:
   answer only from the supplied material; **if the question genuinely isn't
   covered, reply with exactly `OFF_TOPIC` and nothing else**. The question is a
   delimited user turn, never concatenated into the system prompt — the same
   data-not-instructions discipline `grade_free_text` documents. Because the
   context carries nothing privileged (layer 1), a successful injection buys an
   attacker an off-topic answer, not data. **That is the invariant to preserve if
   this design is ever changed.**

3. **Sentinel watch.** The server buffers the leading tokens; if the stream
   starts with the `OFF_TOPIC` sentinel it swallows the rest and emits
   `off_topic`. Otherwise it forwards `delta` events. This is how a stream and an
   on-topic verdict coexist in one request: the embedding gate carries most of
   the load, the sentinel is the model's cheap backstop inside the same call.

On a completed on-topic answer: persist to `card_qa`, increment `ask_usage`.

### The interface method

**`ContentGenerator.stream_card_answer(self, query: CardAnswerQuery) ->
AsyncIterator[str]`** — **single-item and streaming**, an explicit, documented
exception to ADR-0005's "every LLM-facing method takes a collection". The rule's
rationale is request metering — a single-item *batch* entrypoint invites N
requests where one would do. A streamed answer **is** exactly one request, and
there is nothing to batch: one user, one question, arriving at its own time. A
`list[...]` of length one, forever, would be a worse interface, not a safer one.
`GeminiContentGenerator` implements it with an `astream` sibling to
`_invoke_with_retry` that still goes through `acquire()` and `note_request_sent`.
`fake.py` gets a trivial streaming stub. `tests/test_architecture.py` asserts
this is the *only* sanctioned single-item generation method and points here.

## Consequences

**Easier**

- The button does something, with an answer scoped to the card the reader is
  looking at.
- The exchange is cached, so a popular question on a popular card costs one call
  ever.

**Harder**

- **First SSE endpoint.** `StreamingResponse`, client `EventSource` handling,
  and mid-stream error semantics are all new patterns here — the plan's own
  recommendation was non-streaming precisely to avoid this, and this ADR takes on
  that complexity because the owner chose the answer UX.
- **First single-item generation method.** A deliberate, narrow crack in
  ADR-0005's wall, fenced by an architecture test — but a crack.
- The similarity floor is an uncalibrated guess until there is real question
  data (task).
- A stream that dies mid-answer has still spent its request (the ledger counts it
  at `note_request_sent`); the reader sees `error` after some `delta`s. This
  matches how generation already treats a mid-call failure.
- `card_qa` grows roughly with distinct questions asked; small text, a prune task
  if it ever matters.
- The injection posture holds **only while the retrieval context stays free of
  privileged data**. Any future change that adds user-private rows to the context
  breaks "injection only buys an off-topic answer" — guard it.

## Alternatives considered

**MCP server exposing the DB.** The plan's headline rejected option: a protocol
hop, a second deployable, a second place DB access is authorized, and an agentic
loop that costs 3–6 metered requests per question. A read-only admin MCP over the
corpus for the *owner's own* queries is still worth building — off every user
path.

**Two calls: a structured `{on_topic}` verdict, then a streamed answer.** Clean
logic, but two requests per question and ~300 ms extra latency, when the free
embedding gate already catches most off-topic questions and the sentinel gets the
rest in one request.

**Non-streaming structured `{on_topic, answer}`** — the plan's own
recommendation. Simplest, and it fits every other interface method. Not chosen:
the owner wants the answer to stream.

**A quota reservation / generation floor / consumer tag** (earlier plan text,
deleted in `d0b2a7b`). Not reintroduced — recorded here so a future reader
doesn't "restore" it as a missing piece.

**Similarity-match cache** ("close enough" question reuses an answer). Rejected
for v1: exact normalised-string match is predictable; a fuzzy hit risks serving a
subtly wrong answer with confidence.

## Revisit when

- There is real question data to calibrate `ask_ai_topic_similarity_floor`
  against.
- AskAI volume visibly moves the shared quota ladder — then the reservation /
  consumer-tag that `d0b2a7b` removed becomes worth its complexity.
- Someone wants multi-turn follow-ups. That is the agentic-loop shape ADR-0005
  pushes back on; it needs its own ADR, not an extension of this one.
