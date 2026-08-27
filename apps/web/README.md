# apps/web

Next.js + TypeScript. Deployed to **Cloudflare Pages** (not Vercel — the Hobby tier
prohibits commercial use, and we intend to monetize).

## Owns

- Rendering and client state. **That's all.**
- The swipe feed, card expansion, notes, quiz UI, progress and completion surfaces.

## Does not own

**Any business logic.** Zero. It calls `apps/api` over HTTP exactly as the future React
Native app will. If logic creeps in here, the mobile app either can't reach it or we end
up maintaining two divergent implementations. This is the most common way
"we'll add mobile later" projects rot.

## API types

Generated from the API's OpenAPI schema, never hand-written:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o packages/api-types/schema.d.ts
```

This runs in CI. A Pydantic model change that breaks the frontend fails the build.
See [ADR-0001](../../docs/adr/0001-python-fastapi-over-node.md).

## Status

**The feed frontend is finalized.** Everything the reader touches on the home feed is
built and responsive across the full breakpoint ladder
([ADR-0064](../../docs/adr/0064-mobile-shell-tab-bar.md)):

- The swipe feed, card expansion, ASCII / diagram scenes, notes, Ask AI, share, and the
  quiz-taking + quiz-gated progression UI.
- The three-column desktop shell **and** its narrow-viewport form — one component tree,
  CSS re-places the rails: a bottom `MobileNav` tab bar at `<=1100px`, a `MobileTopBar` +
  slide-up Browse sheet at `<=680px`.
- Right-rail controls: the daily-goal ring
  ([ADR-0062](../../docs/adr/0062-daily-goal-ring-and-local-day-semantics.md)), the Theme
  and Font pickers (a labelled dropdown in the docked rail, expanded swatches in the
  sheet), focus mode, the topic filter with per-topic progress on each chip, "View all
  topics" discovery, the per-topic progress box, and inline Discover.
- **Defaults stay Notebook + Literata** (ADR-0012 / ADR-0037). The Theme and Font pickers
  carry a small accent-dot **"developer's pick"** marker on **Obsidian** and **Space
  Grotesk** — a signposted recommendation only; nothing is pre-selected.
- Auth: email/password, Google OAuth, guest sessions
  ([ADR-0033](../../docs/adr/0033-jwt-auth-and-guest-identity.md)); onboarding (topic pick
  + theme pick).

**Being finalized next:** the standalone pages and sections around the feed — Profile,
Settings, Liked, Saved / "Revisit"
([task 0015](../../docs/tasks/0015-topic-mastery-and-retention-mode.md)), notes in one
place ([task 0004](../../docs/tasks/0004-notes-in-one-place.md)) — plus the remaining
right-rail density pass and the personalised "For You" discovery toggle
([task 0028](../../docs/tasks/0028-responsive-right-rail-and-controls.md),
[task 0003](../../docs/tasks/0003-personalized-topic-recommendations.md)) and the palette
picker's onboarding "previews" layout
([task 0002](../../docs/tasks/0002-palette-selection-ui.md)).
