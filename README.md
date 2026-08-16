# Slocho

A swipeable feed of AI-generated knowledge flash cards. Pick topics, get bite-sized
cards at your difficulty level, dig deeper with inline AI chat or personal notes.

Web first; a React Native app comes later and shares this backend.

---

> **Status: early build.** Feed serving, engagement, and the web app's feed (visual design
> in [ADR-0012](docs/adr/0012-feed-visual-design.md)) are live against seeded data.
> Generation, quiz-gated progression UI, and the palette picker (task
> [0002](docs/tasks/0002-palette-selection-ui.md)) are not built yet. Read
> [`docs/architecture/overview.md`](docs/architecture/overview.md) first; it is the mental
> model everything else assumes.

---

## Start here

**Using Claude Code (or another agent) in this repo?** [`CLAUDE.md`](CLAUDE.md) is the
bootstrap it reads automatically every session — what to read first, and the doc-hygiene
rules that keep a new session from re-deriving context that already exists on disk.

| If you want to… | Read |
|---|---|
| Understand how Slocho works | [Architecture overview](docs/architecture/overview.md) |
| Know what a card actually is | [Content model](docs/architecture/content-model.md) |
| See the feed's visual design | [Mockups](docs/design/mockups/) ([ADR-0012](docs/adr/0012-feed-visual-design.md)) |
| Know *why* something is the way it is | [ADR index](docs/adr/) |
| **Find the work assigned to you** | **[Tasks](docs/tasks/)** |
| Add a significant decision | [ADR template](docs/adr/TEMPLATE.md) |

**New here?** Read the architecture overview first, then the ADR index, then your task in
[`docs/tasks/`](docs/tasks/).

## The one thing to internalise

> **The feed read path never touches an LLM.**

A swipe is ~50ms; an LLM call is 2–10 seconds. So Slocho is a **content factory**
(slow, async, batched) filling a **content warehouse** (Postgres), read by a **serving
layer** (fast, no LLM). Cards are generated once and **shared across users** —
personalization is ranking over a shared corpus, not per-user generation.

If that's surprising, read the overview before writing code.

## Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic v2 (async) | [ADR-0001](docs/adr/0001-python-fastapi-over-node.md) |
| Workers | `procrastinate` jobs, batch-run via cron | [ADR-0003](docs/adr/0003-free-tier-first.md) |
| DB | Neon Postgres + pgvector | one store for relational data *and* embeddings |
| ORM | SQLAlchemy 2.0 (async) + Alembic | typed, readable SQL |
| Embeddings | `fastembed` / BGE-small, **local** | free and unlimited; protects LLM quota |
| Generation | Gemini Flash via LangChain, behind `ContentGenerator` | [ADR-0002](docs/adr/0002-langchain-behind-an-interface.md) |
| Web | Next.js + TypeScript → Cloudflare Pages | Vercel Hobby forbids commercial use |
| API types | Generated from OpenAPI, checked in CI | [ADR-0001](docs/adr/0001-python-fastapi-over-node.md) |

## Planned layout

```
apps/api        FastAPI service — the single source of truth for all clients
apps/worker     Background jobs (same codebase as api, different entrypoint)
apps/web        Next.js — rendering and client state only, zero business logic
packages/       Shared contracts, generated API types
docs/           Architecture and ADRs
```

**The rule:** the web app talks to `apps/api` over HTTP exactly as the mobile app
will. No privileged access. If the web client can do something the mobile client
can't, that's a bug.

## Developer experience

Treated as a first-class requirement, not a cleanup task — the previous iteration of
this project was criticised for exactly this. Two measurable goals:

> **Clone → running app with seeded data: one command, under 10 minutes,** on a
> machine that has only Docker and git.
>
> **Clone → merged meaningful change: under a day,** without needing to ask the other
> developer anything.

To hold that line, built in from the start rather than retrofitted:

- `docker compose up` brings up everything. No "first install Python 3.13, then…" prose.
- `make setup` / `make dev` / `make seed` / `make test` — nobody memorizes commands.
- Seed data includes a **pre-generated card corpus fixture**, so a new developer sees a
  working feed without burning LLM quota or waiting on generation. Also seeded: two
  topics from a manual multi-agent generation experiment (`fixtures/generated_corpus.json`,
  loaded by `seed_generated.py`) — a proof-of-concept preview of what the real generation
  pipeline should eventually produce, tagged with its own `gen_meta.backend` so it stays
  distinguishable from the hand-written fixture.
- `.env.example` documents every variable, with safe local defaults.
- FastAPI serves interactive API docs at `/docs`.
- A `README.md` in each package: what it is, what it owns, where to start reading.
- `ruff` + `mypy --strict` + `pre-commit`. Style stops being a conversation.
- CI runs lint, types, tests, and the OpenAPI→TypeScript codegen check on every PR.

The enforcement half matters more than the documentation half: docs rot silently,
a failing CI check does not.

## Team

A two-person project. Anubhav owns architecture, planning, and design; implementation
is split between Anubhav and Mayank.
