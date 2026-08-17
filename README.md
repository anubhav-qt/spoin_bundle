# Spoin → Spoin

A swipeable feed of AI-generated knowledge flash cards. Pick topics, get bite-sized
cards at your difficulty level, dig deeper with inline AI chat or personal notes.

Web first; a React Native app comes later and shares this backend.

---

> **The product is named Spoin.** The tree still says Spoin everywhere, and that is
> deliberate: [ADR-0020](docs/adr/0020-rename-to-spoin.md) commits the rename to a single
> mechanical sweep — package path, imports, database name, docs, mockups — because a
> half-renamed tree makes "which name is current?" a question every future session has to
> answer by reading code. Until task [0007](docs/tasks/0007-rename-to-spoin.md) runs,
> **Spoin is the correct name to use in code and config.** Don't rename opportunistically.

> **Status: early build.** Feed serving, engagement, and the web app's feed (visual design
> in [ADR-0012](docs/adr/0012-feed-visual-design.md)) are live against seeded data. The
> generation pipeline (curriculum, topic merging, card generation — see
> [generation-pipeline.md](docs/architecture/generation-pipeline.md)) is built and runs via
> a CLI; it isn't wired to the worker/cron trigger yet (task
> [0008](docs/tasks/0008-wire-generation-job-worker.md)), and the real quality gate is still
> a stub. Quiz-gated progression UI and the palette picker (task
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
| Understand how Spoin works | [Architecture overview](docs/architecture/overview.md) |
| Know what a card actually is | [Content model](docs/architecture/content-model.md) |
| Know how the corpus gets filled | [Generation pipeline](docs/architecture/generation-pipeline.md) |
| See the feed's visual design | [Mockups](docs/design/mockups/) ([ADR-0012](docs/adr/0012-feed-visual-design.md)) |
| Know why cards are funny on purpose | [ADR-0021](docs/adr/0021-ascii-scene-library.md), [ADR-0022](docs/adr/0022-dual-titles.md) |
| Know *why* something is the way it is | [ADR index](docs/adr/) |
| **Find the work assigned to you** | **[Tasks](docs/tasks/)** |
| Add a significant decision | [ADR template](docs/adr/TEMPLATE.md) |

**New here?** Read the architecture overview first, then the ADR index, then your task in
[`docs/tasks/`](docs/tasks/).

## The one thing to internalise

> **The feed read path never touches an LLM.**

A swipe is ~50ms; an LLM call is 2–10 seconds. So Spoin is a **content factory**
(slow, async, batched) filling a **content warehouse** (Postgres), read by a **serving
layer** (fast, no LLM). Cards are generated once and **shared across users** —
personalization is ranking over a shared corpus, not per-user generation.

If that's surprising, read the overview before writing code.

## The card's personality — decided, partly built

Cards are meant to be funny enough to screenshot and honest enough to be quizzed on.
Those two goals are kept from fighting by one rule:

> **Silliness lives in the hook layer — title, summary, ASCII art. Never in `body`.**

The explanation a user is tested on stays straight prose, which is also what keeps the
quality gate's factual-accuracy and difficulty checks meaningful. What that buys, and what
it costs:

| Decision | Shape |
|---|---|
| [ADR-0021](docs/adr/0021-ascii-scene-library.md) — ASCII scenes | Cards can carry a stickman scene. The generator **picks from a hand-authored catalog and writes the dialogue; it never draws.** Models are unreliable at ASCII art and no quality-gate check can detect a broken drawing — the catalog is what replaces the missing detector. |
| [ADR-0022](docs/adr/0022-dual-titles.md) — two titles | `title` is playful and shown on the feed face; `canonical_title` is literal and is what quizzes, progress lists, search, and the generation prompt read. Make the title playful without this and ADR-0007's duplicate prevention silently stops working. **Built** — schema and generation prompt (not live-verified, see [generation-pipeline.md](docs/architecture/generation-pipeline.md)). |
| [ADR-0023](docs/adr/0023-reader-font-selection.md) — five reader fonts | Same mechanism as the five palettes. `--font-mono` is deliberately **not** part of the choice: ADR-0021's 40-column scenes are only real if the characters are fixed-width. |
| [ADR-0020](docs/adr/0020-rename-to-spoin.md) — the name | Spoin → Spoin, as one atomic sweep. See the banner at the top. |

ADR-0021's scene catalog, ADR-0023's font picker, and ADR-0020's rename are not
implemented. ADR-0022 is. The schema fields ADR-0021 adds exist regardless (so a future
catalog needs no regeneration) — see [content-model.md](docs/architecture/content-model.md).

## Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic v2 (async) | [ADR-0001](docs/adr/0001-python-fastapi-over-node.md) |
| Workers | `procrastinate` jobs, batch-run via cron | [ADR-0003](docs/adr/0003-free-tier-first.md) |
| DB | Neon Postgres + pgvector | one store for relational data *and* embeddings |
| ORM | SQLAlchemy 2.0 (async) + Alembic | typed, readable SQL |
| Embeddings | `fastembed` / BGE-small, **local** | free and unlimited; protects LLM quota |
| Generation | Gemini Flash via LangChain, behind `ContentGenerator` | [ADR-0002](docs/adr/0002-langchain-behind-an-interface.md) |
| Generation orchestration | LangGraph, confined to `generation/pipeline.py` | [ADR-0024](docs/adr/0024-langgraph-for-card-generation-pipeline.md) |
| Web | Next.js + TypeScript → Cloudflare Pages | Vercel Hobby forbids commercial use |
| Typography | Five self-hosted OFL faces, user-selectable; mono locked | [ADR-0023](docs/adr/0023-reader-font-selection.md) |
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
