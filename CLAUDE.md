# Working in this repo

Read this first, every session — it is the bootstrap. It doesn't restate what the docs
already say; it tells you which docs to read and in what order, so a new chat gets useful
fast instead of re-deriving context that already exists on disk.

## Read before doing anything

1. [`docs/architecture/overview.md`](docs/architecture/overview.md) — the mental model
   everything else assumes. **The feed read path never touches an LLM** is the one thing
   to internalise before touching code.
2. [`docs/architecture/content-model.md`](docs/architecture/content-model.md) — what a
   card, subtopic, and quiz question actually are. The highest-leverage schema in the
   project; generation, ranking, and the UI all inherit its shape.
3. [`docs/adr/`](docs/adr/) — skim the index, read any ADR whose title touches what you're
   about to change. **Do not re-litigate a decision that has an ADR** without reading its
   "Alternatives considered" first — the reason something looks suboptimal is usually
   written down.
4. [`docs/tasks/`](docs/tasks/) — open, self-contained work. Check here before assuming
   something is unstarted or unowned.
5. [`docs/design/mockups/`](docs/design/mockups/) — the feed's visual design is real,
   working HTML, not a picture to redraw from. [ADR-0012](docs/adr/0012-feed-visual-design.md)
   explains the decisions behind it.

If a task touches the feed, engagement, or progression specifically, also read
[ADR-0009](docs/adr/0009-quiz-gated-progression.md), [ADR-0010](docs/adr/0010-feed-serving.md),
and [ADR-0011](docs/adr/0011-engagement.md) before writing code — that trio defines rules
(SEEN semantics, event/state/aggregate separation, ranking inputs) that are easy to
accidentally violate from the UI side without realizing it.

If a task touches **card content, titles, or generation prompts**, read
[ADR-0021](docs/adr/0021-ascii-scene-library.md) and [ADR-0022](docs/adr/0022-dual-titles.md)
first. Same reason: both define rules whose violation is *silent*. Free-form ASCII art and
a single playful `title` both look fine on the handful of cards anyone actually eyeballs,
and degrade everywhere else.

## The name is Spoin; the tree still says Spoin

Deliberate, not stale. [ADR-0020](docs/adr/0020-rename-to-spoin.md) commits the rename to
one atomic sweep (task [0007](docs/tasks/0007-rename-to-spoin.md)) covering the package
path, imports, database name, docs, and mockups together.

**Until that task runs, `spoin` is correct in code and config.** Do not rename the files
you happen to be touching — a half-renamed tree costs every future session more than
either end state, because "which name is current?" stops being answerable from the docs.
If you are asked to do the rename, do all of it in one commit and verify with
`grep -ri spoin` returning zero.

## The rules that generalize

**No business logic in `apps/web`.** The web app talks to `apps/api` over HTTP exactly as
the mobile app will. If the web client can do something the mobile client can't, that's a
bug. When in doubt about whether something belongs in a component or the API, it belongs
in the API.

**The generator is trusted for taste, never for constraints.** Anything that must be
*true* — a column budget, a reuse cap, a character limit, a difficulty rating — is
enforced or independently verified outside the model. Anything that merely needs to be
*good* — prose, a punchline, which scene fits an idea — is the model's job. This is one
rule, not three: it is why the quality gate re-rates difficulty instead of trusting the
self-report (content-model.md), why `archetype` is derived rather than requested
([ADR-0017](docs/adr/0017-card-archetypes.md)), and why ASCII scene reuse is counted
server-side rather than asked for in the prompt
([ADR-0021](docs/adr/0021-ascii-scene-library.md)). When you catch yourself adding a
"please keep this under N characters" line to a prompt, you want a check, not a sentence.

**Silliness lives in the hook layer — title, summary, ASCII art. Never in `body`.** The
product's claim is quiz-gated mastery of true things. A joke in the line that stops a
scroll is charm; a joke in the explanation someone is tested on is noise, and it
undermines the gate checks that operate on `body` as meaning.

## Keep the loop closed

This file and the docs it points at are what make a *new* chat efficient — there is no
memory carried between sessions other than what's written down. That only holds if it
stays current:

- **A decision with real reasoning behind it gets an ADR**, not just a comment in code.
  Use [`docs/adr/TEMPLATE.md`](docs/adr/TEMPLATE.md). Number sequentially; check the
  highest existing number in `docs/adr/` first.
- **A decision that changes or partially supersedes an earlier ADR should say so in both
  directions** — a note in the new ADR pointing back, and a note in the old one (or in
  whichever doc stated the superseded rule) pointing forward. Don't silently leave the old
  doc claiming something the code no longer does — see how
  [ADR-0012](docs/adr/0012-feed-visual-design.md) and
  [content-model.md](docs/architecture/content-model.md)'s "Got it" section reference each
  other for the pattern.
- **Deferred work gets a task doc**, not a TODO comment or a line in a chat that will be
  gone next session. Add it to the table in [`docs/tasks/README.md`](docs/tasks/README.md).
- **A visual design decision gets its source-of-truth mockup committed** under
  `docs/design/mockups/`, not left living only in a chat-published artifact link. Artifact
  links are for review during a session; the committed file is what the next session reads.
- **If something in the docs turns out to be stale while you're working**, fix it in the
  same session rather than noting it and moving on. A doc that's wrong is worse than no doc
  — it actively costs the next session time instead of saving it.

## Stack quick reference

See the README for the full table. The short version: FastAPI + SQLAlchemy async on
Postgres/pgvector, Next.js + TypeScript on the web side, generation behind a
`ContentGenerator` interface, everything free-tier-first (ADR-0003) until it isn't.

`docker compose up` brings up the full stack with seeded data — the fastest way to see
real cards render rather than guessing from schema alone.
