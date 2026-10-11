# ADR-0106: Spoin moves to TypeScript on Hono, and a 24/7 pi harness authors the universe and its cards

- **Status:** Accepted (supersedes 0002, 0094; amends 0001, 0006, 0007, 0009, 0010, 0025, 0077, 0084, 0088, 0090, 0092, 0103, and the Antigravity authoring track)
- **Date:** 2026-10-11
- **Deciders:** owner (every decision below is the owner's, asked one by one), Claude

## Context

On 2026-10-11 the system had never been deployed. The v1 finish-line plan was still
"proposed, not started", `/admin/*` and `/dev/*` existed only outside production because
there was no admin role (task 0035), generation was a manual run on the owner's GPU
(ADR-0094), and the corpus was authored by hand by another agent (Antigravity) following
`docs/the_spoin_universe/procedure.md`.

Meanwhile every other project the owner runs had converged on one shape, and it works in
production:

- **breader**: Hono + Drizzle + Better Auth + zod, npm workspaces, one image with `api`,
  `worker` and `migrate` entrypoints, a token-gated status page fed by a `job_runs`
  table, and a 24/7 AI marker on NVIDIA NIM behind a small balancer that was itself
  adapted from spoin's ADR-0084.
- **POM's Seelie and Trotter**: a hard fork of pi (`pi-ai` + `pi-agent`) reaching the
  owner's subscriptions through CLIProxyAPI, long-running chats with compaction, a
  wake queue in the database, versioned records, an Auditor and a Lessons chat.

About half of `apps/api` (12.5k of 26.5k lines) was the generation write path:
LangGraph, LangChain, the Gemini quota machinery, the Mistral client. A pi harness
replaces all of it, which made a port mostly a port of the read path.

The target is Oracle Cloud's free tier: one ARM machine with 12 GB of RAM and no GPU,
holding all the data for now. Everything is tested in local Docker first.

> **Revised 2026-10-11:** spoin is hosted on the owner's ThinkPad instead. Oracle's
> free tier takes Paribelle, moved off the ThinkPad (task 0045, Phases 12-13).

## Decision

**The stack.**

- Everything is TypeScript on Node 24. npm workspaces, breader-style:
  `apps/server` (Hono: the API, the worker and the migrator as entrypoints of one image),
  `apps/web` (Next.js, unchanged except `lib/api.ts` and login),
  `packages/shared` (the zod wire contract), `packages/frog` (the corpus library),
  `packages/pi-ai` and `packages/pi-agent` (the harness fork).
- The contract is zod in `packages/shared`, used by both sides. The server declares routes
  with `@hono/zod-openapi` and serves an OpenAPI document, which is what a non-TS client
  (the React Native app) generates from. This replaces `packages/api-types` (ADR-0001).
- The HTTP surface is ported 1:1: same paths, same JSON field names, errors as
  `{detail}`. The web app keeps working without a rewrite.
- Drizzle + `pg`. **Two databases stay** (ADR-0088): the app's and `the_spoin_universe`,
  each with its own migrations folder. frog still never imports spoin.
- Auth is Better Auth: email and password, Google, anonymous guests linked on claim,
  bearer tokens for the mobile client, and an admin role (which closes task 0035).
- Embeddings run in-process: `Qwen3-Embedding-0.6B` as ONNX on the CPU, ARM64 included.
  The model is unchanged and every vector is re-embedded once, because ONNX output is not
  byte-identical to sentence-transformers' and ADR-0097 allows one vector space.
- Background work is our own queue table plus `job_runs`, no job library.
- Biome lints and formats; vitest runs against real Postgres, keeping the existing rule
  that the database's own behaviour is tested against the database.

**The harness.** Generation is rebuilt, not ported. The LangGraph pipeline is deleted and
its prompts, canon and validators are reused.

- Built on Trotter's pi fork with image input added back, because sourcing an image means
  looking at it.
- Models come from CLIProxyAPI (Gemini through the owner's Antigravity sign-ins) and
  NVIDIA NIM, behind a breader-style balancer. The accounts are shared with breader,
  Seelie and Trotter.
- Every chat is long-running and Trotter-shaped: woken from a queue in the database,
  compacted when full, every run's messages and tool calls stored, every change a
  versioned record.
- The chats are called **tadpoles**; the manager is **toad_sage**:
  - **toad_sage** (the manager): takes a topic off the queue and does the intake the
    procedure's Phase A asked the owner for: category, sub-category, and the topic's
    scope and card count (see "Scope" below).
  - **Curriculum**: writes the topic's curriculum against the corpus.
  - **One chat per topic**: runs that topic's pipeline (research, corpus, images) and
    then its data generation (cards and questions).
  - **Feedback**, as in Trotter: an Auditor that reads every run, and lessons kept from
    every failure and fed back into the chats' instructions. (Revised 2026-10-11: the
    Auditor is named ero_sennin; every chat's tools are in
    [harness-tools.md](../architecture/harness-tools.md).)
  - **Frogs**: a topic's tadpole becomes its frog once the topic's first generation is
    live in production. Later updates and feedback-driven improvements to that topic run
    in its frog. (Not `packages/frog`, the retrieval library of ADR-0087: same word,
    different thing.)
  - **User feedback goes to the frogs.** The card reports of ADR-0076 are kept as they
    are and routed automatically to the frog of the card's topic. The frog first judges
    whether a report is genuine, comparing it with earlier reports in a similar style or
    from the same usernames to tell safe from suspicious. A genuine one it implements:
    a new version of the card in the same family, which replaces the old one in
    production.
  - **Cards are written once.** A topic's first generation is its whole set of cards
    (ADR-0026's one-shot run, kept); after that the only rewrites are a frog's new
    versions of reported cards. A reader masters a topic and moves on to the next, so
    nothing writes more cards for a topic on demand and a short feed page enqueues
    nothing. A reader who has read every card is served them again with `recycling`
    set, so the repeat is announced rather than silent (ADR-0006). The web's notices
    that promise more cards on the way (short page, second pass, end of feed) are
    rewritten in the web rewire.
  - **Scope: survey, topic or one-shot.** `is_survey` becomes one enum, `scope`, in
    both databases: the app's `topic.scope` and the corpus's `document_scope` (on
    `document` and `curriculum`), equal by value because frog does not import the
    app's contract. Only `topic` keeps three tiers (ADR-0009). A survey and a one-shot
    are **tierless**: the feed serves their cards easy to advanced with no mix
    (ADR-0010), and a card scrolled past comes back only once the whole topic has
    nothing unseen; progress is the weakest subtopic's coverage across the whole
    topic; and one mastery quiz, its MCQs split evenly across difficulties with a short
    difficulty topped up from the others, unlocks at the usual 80% gate. Passing it
    masters the topic. The quiz is recorded in the advanced slot of the per-tier
    progress arrays, so content-model.md's "mastered" keeps one definition, and a
    tierless topic ignores the follower's entry tier and always shows `beginner`.
  - **The harness picks each topic's scope and card count** from the data and the
    instructions it is given. 125-750 cards per topic is one of those instructions;
    no code rejects a topic outside it.
  - **AskAI is a chat of its own per reader per topic** (amends ADR-0077). The single
    streamed call over server-assembled context becomes a long-running pi chat, one
    per `ask_conversation`, that keeps its own transcript and compaction, so the server
    no longer resends the thread. It reads the topic through read-only tools the server
    hands it with each turn: the topic and its subtopics, this topic's active cards,
    a search over them by embedding, and a search over the corpus sections this topic
    and the topics joined to it by a `topic_edge` were grounded in, through frog
    retrieval. It
    is given no user id and no database handle, so ADR-0077's invariant holds: a
    successful injection buys an off-topic answer, never data. The server keeps the
    thread the reader sees, the SSE events, the card hint (an active card of this
    topic, otherwise none), the 200 turns a day and the `OFF_TOPIC` sentinel. The
    embedding pre-check is dropped, so every turn reaches the chat, and a refused turn
    counts against the 200 like an answered one; a failed turn does not. The search
    tool still embeds on the request path, so ADR-0092's CPU embedder stays.
  - **Records live in Postgres, not in context.** Everything any agent flags or judges
    (report verdicts, safe or suspicious reporters, failures, lessons) is a row. Agents
    look past records up through tools when they need them instead of carrying them in
    their context, so a judgment rests on what was actually recorded, never on a
    remembered or invented history.
  - **Tool errors teach.** Every error an agent gets back from a tool is one short line
    saying what was wrong and how to call it right, so a failed call is followed by a
    good one. A tool reports a wrong call by throwing `ToolError`, and the harness hands
    its message back as the call's result; any other failure is logged in full and the
    agent gets a short line, never a stack trace. A call that half-succeeds returns what
    it could, with a note naming what it couldn't.
- **Nothing waits on the owner.** Before anything goes live, a separate model call runs a
  verification checklist written with the owner. What passes goes live; the owner
  audits afterwards.
- Topics come from a queue the owner fills in admin, and user requests feed the same
  queue from the start. A name with no exact alias match becomes a pending topic, the
  requester's custom subscription and a generate job; toad_sage then validates it,
  merges it into an existing topic, or rejects it with a reason the user sees. No model
  runs inside the request, which amends ADR-0025's synchronous name check.

**Operations.** All admin lives in the Next.js app behind the admin role, status included.
The new system starts from empty databases in its own compose project and its own
volume, so nothing it does can touch `spoin_db_2`. The Python code is deleted once the TS
server passes its ported tests; git history keeps it.

## Consequences

- One language and one contract from the database to the browser, and the owner's
  proven ops patterns apply directly.
- The production server stops being "minimal" (ADR-0094 is superseded): it runs the
  harness, the embedder and CLIProxyAPI. 12 GB has to hold Postgres, Node, a 0.6B ONNX
  model and the proxy, so memory caps per container are part of the compose file, not
  an afterthought.
- No GPU anywhere in production. Bulk embedding is CPU-bound and slower. That is
  acceptable for a corpus measured in thousands of chunks, not millions.
- Every test guarantee the Python suite gave is gone until its TS port lands. Tests are
  ported with each package, not after.
- Using subscriptions through CLIProxyAPI may go against the providers' terms and can be
  blocked (Trotter's ADR 0005 says the same). NIM is the second leg, and a paid key is
  the fallback that needs no code change.
- CLAUDE.md's rule still binds: **measure a provider's concurrency behaviour before
  building on it.** Neither CLIProxyAPI-Gemini nor NIM has been measured from spoin.
- Today's 605 cards stay in `spoin_db_2` and its Neon copy; the new system does not
  carry them over.

## Alternatives considered

- **Keep the Python API and add only a TS harness.** Faster to production, but two
  languages and two schema systems (Pydantic and zod) forever, and torch on the server.
  The owner chose one stack.
- **Hono RPC (`hc<AppType>`) instead of OpenAPI.** End-to-end types with no codegen, but
  it ties every client to TypeScript, and type-checking slows as routes grow.
- **Port the LangGraph pipeline 1:1 and add the harness later.** Less redesign up front,
  but it ports 12.5k lines that the harness then replaces.
- **pg-boss for jobs.** Proven, but the queue the harness needs is the one Trotter
  already shows: one table we can read in admin.

## Revisit when

- A provider through CLIProxyAPI blocks the accounts, or NIM's free API changes terms.
- The 12 GB machine runs out of memory under the harness plus the API.
- The corpus grows past what CPU embedding re-embeds in an acceptable time.
