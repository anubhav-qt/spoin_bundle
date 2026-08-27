<p align="left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="apps/web/public/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="apps/web/public/logo-light.svg">
    <img src="apps/web/public/logo-light.svg" alt="spoin" width="160">
  </picture>
</p>
A scrollable feed of cards with bite sized knowledge, for topics you want to learn (choose either from the presets or your own choice of topics), with an entire planned curriculum and a road to mastery. Pick topics, get bite-sized
cards at your difficulty level, dig deeper with inline AI chat or personal notes.

Web first; a React Native app comes later and shares this backend.

---

> **Status: early build.** Feed serving, engagement, the quiz-taking UI, and real JWT
> auth (email/password + Google OAuth + guest sessions; see
> [ADR-0033](docs/adr/0033-jwt-auth-and-guest-identity.md)) are live against `spoin_db`,
> which holds real verified production data from the generation pipeline (seeded mock
> data has been purged; see [generation-pipeline-test-run.md](docs/architecture/generation-pipeline-test-run.md),
> [generation-pipeline-run-3-benchmark.md](docs/architecture/generation-pipeline-run-3-benchmark.md)
> for the 10,000+ card milestone, and `CLAUDE.md`).
> The web app's feed visual design is in [ADR-0012](docs/adr/0012-feed-visual-design.md).
> The generation pipeline (curriculum, topic merging, card generation, the two-pass
> quality gate; see [generation-pipeline.md](docs/architecture/generation-pipeline.md) and
> [ADR-0030](docs/adr/0030-two-pass-quality-gate.md)) is built, tested, and wired to
> `apps/worker` (task [0008](docs/tasks/0008-wire-generation-job-worker.md), done). The
> palette picker (task [0002](docs/tasks/0002-palette-selection-ui.md)) is not built yet.
> The **web feed frontend is finalized** — the swipe feed, the quiz UI, and the responsive
> shell all the way down to a mobile tab bar and a Browse sheet
> ([ADR-0064](docs/adr/0064-mobile-shell-tab-bar.md)); see
> [`apps/web/README.md`](apps/web/README.md) for the full surface. The standalone pages
> around it (Profile, Settings, Liked, Saved, Notes) are being finalized next.
> Read [`docs/architecture/overview.md`](docs/architecture/overview.md) first; it is the
> mental model everything else assumes.

---

## Start here

**Using Claude Code (or another agent) in this repo?** [`CLAUDE.md`](CLAUDE.md) is the
bootstrap it reads automatically every session: what to read first, and the doc-hygiene
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
layer** (fast, no LLM). Cards are generated once and **shared across users**:
personalization is ranking over a shared corpus, not per-user generation.

If that's surprising, read the overview before writing code.

## The card's personality: decided, partly built

Cards are meant to be funny enough to screenshot and honest enough to be quizzed on.
Those two goals are kept from fighting by one rule:

> **Silliness lives in the hook layer: title, summary, ASCII art. Never in `body`.**

The explanation a user is tested on stays straight prose, which is also what keeps the
quality gate's factual-accuracy and difficulty checks meaningful. What that buys, and what
it costs:

| Decision | Shape |
|---|---|
| [ADR-0042](docs/adr/0042-freeform-ascii-and-real-hero-mechanism.md): ASCII scenes | Cards can carry a stickman scene, **drawn by the generator directly** (superseding [ADR-0021](docs/adr/0021-ascii-scene-library.md)'s never-authored hand-drawn catalog). A 40-column width budget is enforced server-side, not prompted -- an over-budget line drops the visual and keeps the card. |
| [ADR-0022](docs/adr/0022-dual-titles.md): two titles | `title` is playful and shown on the feed face; `canonical_title` is literal and is what quizzes, progress lists, search, and the generation prompt read. Make the title playful without this and ADR-0007's duplicate prevention silently stops working. **Built**: schema and generation prompt (not live-verified, see [generation-pipeline.md](docs/architecture/generation-pipeline.md)). |
| [ADR-0023](docs/adr/0023-reader-font-selection.md): five reader fonts | Same mechanism as the five palettes. `--font-mono` is deliberately **not** part of the choice: ASCII scenes are only real if the characters are fixed-width. **Built** ([ADR-0037](docs/adr/0037-site-wide-font-picker.md)). |

ADR-0022, ADR-0023's font picker, and ADR-0042's generator-drawn scenes are all implemented.
See [content-model.md](docs/architecture/content-model.md).

## Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic v2 (async) | [ADR-0001](docs/adr/0001-python-fastapi-over-node.md) |
| Workers | `procrastinate` jobs, batch-run via cron | [ADR-0003](docs/adr/0003-free-tier-first.md) |
| DB | Neon Postgres + pgvector | one store for relational data *and* embeddings |
| ORM | SQLAlchemy 2.0 (async) + Alembic | typed, readable SQL |
| Embeddings | `fastembed` / BGE-small, **local** | free and unlimited; protects LLM quota |
| Generation | Gemini Flash via LangChain, behind `ContentGenerator` | [ADR-0002](docs/adr/0002-langchain-behind-an-interface.md) |
| Generation orchestration | LangGraph, confined to `generation/pipeline/`'s `graph.py` + `nodes.py` | [ADR-0024](docs/adr/0024-langgraph-for-card-generation-pipeline.md), [ADR-0044](docs/adr/0044-generation-pipeline-as-a-package.md) |
| Web | Next.js + TypeScript → Cloudflare Pages | Vercel Hobby forbids commercial use |
| Typography | Five self-hosted OFL faces, user-selectable; mono locked | [ADR-0023](docs/adr/0023-reader-font-selection.md) |
| API types | Generated from OpenAPI, checked in CI | [ADR-0001](docs/adr/0001-python-fastapi-over-node.md) |

## Planned layout

```
apps/api        FastAPI service, the single source of truth for all clients
apps/worker     Background jobs (same codebase as api, different entrypoint)
apps/web        Next.js, rendering and client state only, zero business logic
packages/       Shared contracts, generated API types
docs/           Architecture and ADRs
```

**The rule:** the web app talks to `apps/api` over HTTP exactly as the mobile app
will. No privileged access. If the web client can do something the mobile client
can't, that's a bug.

## Developer experience

Treated as a first-class requirement, not a cleanup task; the previous iteration of
this project was criticised for exactly this. Two measurable goals:

> **Clone → running app, one command, under 10 minutes,** on a machine that has
> only Docker and git.
>
> **Clone → merged meaningful change: under a day,** without needing to ask the other
> developer anything.

To hold that line, built in from the start rather than retrofitted:

- `docker compose up` brings up everything. No "first install Python 3.13, then…" prose.
- `make setup` / `make dev` / `make seed` / `make test`: nobody memorizes commands.
- **`spoin_db` is the one dev database this project uses, and it starts and stays
  blank** -- `docker compose up`'s `seed` service only runs migrations now, no
  fixture loading. This reverses the project's earlier "seeded data out of the
  box" onboarding promise: a fresh `docker compose up` gets you an empty feed,
  not a pre-populated one, until real requests populate it. `fixtures/*` and
  `seed_generated.py`/`seed_quiz.py` still exist and still work (`make seed`'s
  old fixture-loading behavior can be run by hand if you want that back for
  your own machine) but are no longer wired into the default flow. See
  `CLAUDE.md` for the reasoning and the rule that goes with it: nobody resets,
  reseeds, or otherwise mutates `spoin_db`'s data without the project owner's
  explicit approval first -- that includes AI agent sessions.
- `.env.example` documents every variable, with safe local defaults.
- FastAPI serves interactive API docs at `/docs`.
- A `README.md` in each package: what it is, what it owns, where to start reading.
- `ruff` + `mypy --strict` + `pre-commit`. Style stops being a conversation.
- CI runs lint, types, tests, and the OpenAPI→TypeScript codegen check on every PR.

The enforcement half matters more than the documentation half: docs rot silently,
a failing CI check does not.

## Automated Background Topic Generation & Idle Scanner

Spoin includes an automated scanning and generation runner (`spoin.scan_and_generate`) that finds incomplete topics in `spoin_db` (topics without curricula or subtopics with active cards below target) and runs the generation pipeline automatically when the machine or server is idle.

### Linux Production Deployment (Crontab / Systemd)

#### Option 1: Standard Linux Crontab (Every 15 Minutes)
```bash
# Edit crontab
crontab -e

# Run one generation pass every 15 minutes:
*/15 * * * * cd /opt/spoin/apps/api && PYTHONPATH=src SPOIN_DATABASE_URL="postgresql+asyncpg://spoin:spoin@localhost:5432/spoin_db" python3 -m spoin.scan_and_generate --limit 1 >> /var/log/spoin-scan.log 2>&1
```

#### Option 2: Linux `systemd` Service & Timer
```bash
sudo cp scripts/systemd/spoin-scan.service /etc/systemd/system/
sudo cp scripts/systemd/spoin-scan.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spoin-scan.timer
```

#### Option 3: Continuous CPU Idle Daemon (Linux / Windows)
Monitors system CPU utilization via `psutil`. When the system CPU has been continuously idle (<15% utilization) for 15 minutes, it triggers a generation pass:
```bash
# Linux
nohup ./scripts/start_idle_runner.sh 15 15.0 1 > /var/log/spoin-idle.log 2>&1 &

# Windows PowerShell
.\scripts\start_idle_runner.ps1 -Background
```

#### Option 4: Docker / Makefile One-Off Scan
```bash
make scan
# Or on Windows without make:
.\make.ps1 scan
```

## Team

A two-person project. Anubhav owns architecture, planning, and design; implementation
is split between Anubhav and Mayank.
