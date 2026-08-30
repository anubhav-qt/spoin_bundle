# ADR-0077: AskAI — a topic-scoped, persistent, streamed conversation over deterministic retrieval

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Anubhav

> **Revised 2026-08-30 (same session, before any frontend shipped).** Two owner
> changes after the first draft: (1) the assistant's scope is **the whole topic**,
> not one card — the card the reader is on is context, not the boundary — and it
> is meant to widen to connected topics once the recommender exists; (2) it is a
> **persistent multi-turn conversation**, not a one-off question. The
> single-exchange `card_qa` cache is replaced by an `ask_conversation` /
> `ask_message` thread. Everything else below (no MCP, no quota partition, SSE +
> `OFF_TOPIC` sentinel, the injection posture) is unchanged. The pre-revision
> Decision is in git history at the commit that first added this file.

## Context

The card action row has an "Ask AI" button (`Card.tsx`) that records an `ask_ai`
engagement event and otherwise does nothing. B12/B13 on the finish-line plan is
to make it a working assistant a reader can ask about what they are learning.

The plan settled the mechanism:

- **Not an MCP server over the database.** MCP exists so an *external* agent can
  discover tools; here the caller is our own backend with the SQLAlchemy models
  already loaded. A DB-access tool driven by user text, on a path that returns to
  the user, is a prompt-injection target with a data-exfiltration payoff. And a
  tool-calling loop is 3–6 requests per turn, which fights ADR-0005's "the free
  tier meters requests" premise.
- **Deterministic retrieval.** The server assembles the context itself with plain
  queries and makes one flash-lite call per conversation turn through the
  existing quota governor. Off-topic questions are held out by structural
  context-scoping, a hard system prompt, a free local-embedding pre-check, and a
  self-declared `OFF_TOPIC` sentinel.

Two standing constraints:

- **No quota partitioning (`d0b2a7b`).** 33 keys × 2 flash-lite models × 500/day
  ≈ 33k requests/day is ample for AskAI and generation together, so they draw
  from the **same** ladder with no reservation, no floor, no consumer tag. The
  only limit is **200 assistant turns per user per day**.
- **Streamed.** The answer streams token by token, which rules out a structured
  `{on_topic, answer}` verdict object — the reconciliation is the sentinel below.

## Decision

### Scope: the topic, and a conversation

The assistant answers about **the whole topic** the reader is in — every one of
its subtopics and cards — not just the card whose button was tapped. The current
card is passed only as a "the reader is currently on: …" hint in the system
prompt. This is deliberately forward-compatible: when the recommender lands,
connected topics' material joins the retrieval set with no shape change here.

It is a **persistent conversation**. One active `ask_conversation` per
`(user_id, topic_id)`; each user question and each assistant answer is an
`ask_message` turn on it. Re-opening the panel resumes the thread. A "start over"
action archives the active conversation and opens a fresh one.

### Tables

**`ask_conversation`** — `(id, user_id, topic_id, status, created_at,
last_message_at)`, partial-unique on `(user_id, topic_id) WHERE status =
'active'` so there is exactly one active thread per topic per user. `status` is
`active | archived`.

**`ask_message`** — `(id, conversation_id, role, content, on_topic, created_at)`.
`role` is `user | assistant`. `on_topic` is only meaningful on an assistant row:
`false` when the turn was refused (embedding gate or sentinel) — the client
renders the refusal state and the model's own prose is never stored or shown.

**`ask_usage`** — unchanged: `(day, user_id, questions_spent)`, PK `(day,
user_id)`, a plain per-user daily counter (NOT the quota governor). `day` is the
UTC day, matching `quota_ledger`. `Settings.ask_ai_daily_limit` defaults to 200.
Only an assistant turn that actually reached the provider increments it — a
gate refusal and an `error` cost nothing and count nothing. There is **no
exchange cache**: a conversation turn depends on the whole thread before it, so
exact-match caching does not apply; the daily cap is the only limiter.

### Endpoints

| method | path | purpose |
|---|---|---|
| `GET` | `/topics/{topic_id}/ask` | the active conversation's messages (empty list if none yet) + `{spent, limit}` |
| `POST` | `/topics/{topic_id}/ask` | body `{question, card_id?}` → **SSE**; appends the user turn, streams the assistant turn, appends it |
| `POST` | `/topics/{topic_id}/ask/reset` | archive the active conversation, 204 |

`POST /topics/{topic_id}/ask` is the **first streaming endpoint in the
codebase**. SSE events:

| event | payload | meaning |
|---|---|---|
| `delta` | `{text}` | a chunk of the assistant turn |
| `done` | `{}` | turn complete |
| `off_topic` | `{hint}` | not answerable from this topic's material; `hint` names what the topic covers |
| `limit` | `{}` | the user hit 200 turns today |
| `error` | `{cause}` | the call couldn't be placed — `cause` is the ADR-0065 distinction, never folded into `off_topic` |

### Retrieval — deterministic, per turn

For each user turn the server assembles: the topic (name + description); its
subtopic list (titles + descriptions); the top-k cards across the whole topic
nearest the question by `content_embedding` (k = `ask_ai_context_neighbours`,
raised from the card-scoped default since the pool is now the topic); the current
card in full if a `card_id` hint was sent; and **the conversation history so
far** (every prior turn, oldest first). No search tool, no browser, no other
users' rows, no other topics (until the recommender adds them explicitly).

### The off-topic gate, per turn, in one request

1. **Embedding pre-check — free, no LLM.** Embed the question; take the max
   cosine similarity against the topic embedding and the nearest retrieved
   cards' embeddings. Below `Settings.ask_ai_topic_similarity_floor` → emit
   `off_topic`, append a refused assistant turn, close. No call, no cap
   increment. The floor is an uncalibrated default with a calibration task (like
   ADR-0001); skipped entirely under the `HashEmbedder` stand-in, exactly as the
   accent-colour and ASCII features already handle a non-real embedder.
   *Follow-up turns in an already-on-topic conversation get a lower effective
   floor* — a terse "why?" is on-topic in context even though it is off-topic in
   isolation.

2. **One streamed flash-lite call** through the `_generator` `QuotaGovernor`
   pool (no reservation). The system prompt names the topic, lists its
   subtopics, notes the current card, and instructs: answer only from the
   supplied material and the conversation so far; **if a question genuinely
   isn't covered, reply with exactly `OFF_TOPIC` and nothing else**. History and
   the new question are delimited user/assistant turns, never concatenated into
   the system prompt — the `grade_free_text` data-not-instructions discipline.
   Because the context carries nothing privileged, a successful injection buys an
   attacker an off-topic answer, not data. **That is the invariant to preserve.**

3. **Sentinel watch.** The server buffers the leading tokens; a stream that
   starts with `OFF_TOPIC` is swallowed and re-emitted as `off_topic`. Otherwise
   tokens forward as `delta`. This is how streaming and an on-topic verdict
   coexist in one request.

On a completed on-topic turn: append the assistant `ask_message`, bump
`last_message_at`, increment `ask_usage`.

### The interface method

**`ContentGenerator.stream_topic_answer(self, query: AskTurnQuery) ->
AsyncIterator[str]`** — **single-item and streaming**, the one explicit,
documented exception to ADR-0005's "every LLM-facing method takes a collection".
The rule's rationale is request metering; a streamed turn **is** exactly one
request and there is nothing to batch — one user, one turn, at its own time.
`AskTurnQuery` carries the topic name, subtopic list, current-card hint, the
assembled retrieval `context`, and `history: list[(role, text)]`.
`GeminiContentGenerator` implements it with an `astream` failover simpler than
`_invoke_with_retry` (a user-facing call fails fast rather than grinding the
grid). `fake.py` gets a trivial streaming stub. `tests/test_architecture.py`
pins it as the only sanctioned single-item generation method.

## Consequences

**Easier**

- The button opens a real assistant for the topic the reader is working through,
  with memory across the session and across re-opens.
- Widening to connected topics later is a retrieval-set change, not an API change.

**Harder**

- **First SSE endpoint** — `StreamingResponse`, client `EventSource`, mid-stream
  error semantics, all new here.
- **First single-item generation method** — a deliberate, narrow crack in
  ADR-0005's wall, fenced by an architecture test.
- **Context grows with the conversation.** Every turn re-sends the whole thread.
  The free tier meters requests not tokens (ADR-0003), so this costs latency and
  context-window headroom, not quota — but a very long thread will eventually
  need truncation (oldest turns dropped, or summarised). Not built now; the
  `ask/reset` action is the manual escape hatch.
- The similarity floor is an uncalibrated guess (task).
- A turn that dies mid-stream has still spent its request; the reader sees
  `error` after some `delta`s, same as generation treats a mid-call failure.
- No cache: a popular opening question is paid for once per user, not once ever.
  Acceptable at the 200/user/day cap; revisit if it bites.
- The injection posture holds **only while the retrieval context stays free of
  privileged data** — guard any future change that adds user-private rows.

## Alternatives considered

**Card-scoped, single-exchange (the first draft of this ADR).** Simpler — a
`card_qa` exact-match cache, no conversation state, retrieval bounded to one
card. Rejected by the owner: readers ask about the thing they are learning, which
is the topic, and a question usually has follow-ups.

**MCP server exposing the DB.** Protocol hop, second deployable, second authz
surface, an agentic loop of 3–6 metered requests per turn. Rejected. A read-only
admin MCP over the corpus for the *owner's own* queries is still worth building,
off every user path.

**Multiple named threads per topic (ChatGPT-style history).** More UI, more
state, little value at v1 — one resumable thread per topic with a "start over"
covers the need. Revisit if users want to keep parallel threads.

**Non-streaming structured `{on_topic, answer}`** — fits every other interface
method. Not chosen: the owner wants the answer to stream.

**A quota reservation / generation floor / consumer tag** (deleted in
`d0b2a7b`) — not reintroduced; recorded so a future reader doesn't "restore" it.

**Agentic multi-tool retrieval loop.** The shape ADR-0005 pushes back on —
3–6 requests per turn, unbounded. Deterministic retrieval + conversation history
gets the multi-turn feel at one request per turn.

## Revisit when

- Real question data exists to calibrate `ask_ai_topic_similarity_floor`.
- Conversations run long enough that context-window pressure is real — add
  history truncation/summarisation.
- The recommender ships — connected topics join the retrieval set.
- AskAI volume visibly moves the shared quota ladder — the reservation
  `d0b2a7b` removed becomes worth its complexity again.
