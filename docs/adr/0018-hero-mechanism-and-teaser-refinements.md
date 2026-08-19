# ADR-0018: Real hero mechanism, teaser refinements, block-expand modal

- **Status:** Accepted
- **Amended by:** [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md) -- the real
  `is_hero`-setting mechanism this ADR deferred to task 0006 (see "`card.is_hero` replaces
  the 'first card in station' heuristic" below) is now built: a dedicated generation-time
  call, not a curation step. The fixture seeder's placeholder, described below, is
  unaffected for fixture-seeded data.
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

A follow-up pass on ADR-0017, after reviewing the card-archetype design gallery and
approving its direction. This ADR covers the pieces that moved from "prototyped in the
review artifact" to "built for real," plus a couple of items that came up only once the
real implementation was underway.

## Decision

### `card.is_hero` replaces the "first card in station" heuristic

ADR-0017 shipped hero rendering with a known-weak placeholder: the frontend treated
whichever card happened to be first in a feed *station* as hero. Two problems with
that, beyond just being a placeholder: a mixed-feed station groups by **topic**, which
can span several subtopics, so "first in station" was never really "one per subtopic"
even as an approximation; and it was purely a rendering-time accident of pagination,
not a decision anyone made.

`card.is_hero` (migration `0da808ae4efd`) is now a real column, returned by `/feed`,
and the frontend (`Feed.tsx`) reads `card.is_hero` directly instead of computing
anything. Today's only writer is the fixture seeder -- it marks the first card listed
per subtopic in `corpus.json`. That's still a placeholder for the real mechanism
(docs/tasks/0006 -- a content-planning step designating one hero per subtopic on
purpose), but it's now a real, inspectable, backend-owned fact instead of a frontend
guess, and the seeder's own fixture ordering can be deliberately curated (see: the
Kubernetes "kubectl apply" diagram card was reordered to be first in its subtopic
specifically so the hero example in the running app is a genuine diagram-tagged card,
not fabricated content).

### Archetype teaser refinements

- **Code + diagram combo.** A card tagged with both `code` and `diagram` no longer
  picks one via priority order for its collapsed teaser -- it shows both, stacked (code
  line over diagram breadcrumb, hairline divider between), which also happens to solve
  more of the "monotonous card heights" problem than either alone.
- **Comparison teaser minimized.** The original comparison teaser leaked the actual
  claim text (occasionally with unparsed `**bold**` markers showing literally -- a bug
  fixed earlier, but the deeper issue was that showing the claim at all defeats the
  point of a *teaser*). Replaced with a small "Myth vs Fact"-style badge that signals
  the card contains a comparison without previewing either side of it.
- **Multi-block cap.** A card can legitimately have more than one fenced code block or
  diagram in its body. Only the first of each kind renders -- anywhere, not just in the
  collapsed teaser. Additional fences of an already-rendered kind are silently
  dropped rather than falling back to a degraded rendering. This is a deliberate
  simplification, not a bug: content generation should avoid stuffing multiple code
  examples into one card in the first place, and the renderer staying predictable if
  it happens anyway is worth more than trying to render an unbounded number of blocks
  well.

### Block-expand modal

Code blocks and diagram blocks both get a small header with an expand button
(top-right), opening the block full-size in a modal -- reusing the existing
`.modal-overlay`/`.modal-panel` chrome and portal pattern already established by
`TopicStatsModal.tsx`, with a wider variant for code/diagram content than that
modal's original 380px topic-detail width.

### Dev-only reset endpoint

`POST /dev/reset` (new `dev.py` router) resets the demo user back to a fresh-feeling
state on demand: clears seen-state (coverage back to 0%), clears the feed's
pagination cursor (`FeedPlan`/`FeedSlate` -- this also fixes the "exhausted feed"
problem repeated manual testing kept running into this session), resets every
followed topic's progress to beginner/nothing-unlocked, and unfollows two randomly
chosen topics so Discover has something to show again. Wired to the "spoin"
wordmark in the left rail as a click -- an easter egg, not a labeled button in any of
the three rails, per how it was asked for. **Explicitly flagged in the router's own
docstring as dev-only** -- it mutates a user's entire state behind nothing but the
placeholder `X-User-Id` auth every other endpoint already has, and must be gated or
removed before anything resembling a public launch.

## Consequences

**Easier**
- Hero is now a real, queryable fact -- `docs/tasks/0006`'s eventual real mechanism
  only has to change how `is_hero` gets SET, not touch the frontend at all.
- Manual testing/demo can reset to a clean state in one click instead of a database
  reset.
- Combo and comparison teasers read as more varied and less leaky, respectively.

**Harder**
- `is_hero`'s "at most one per subtopic" invariant is not DB-enforced -- only true by
  construction in the seeder today. A future real writer (or a bug in one) could
  violate it silently. Worth a partial unique index once a real writer exists.
- The multi-block cap means content that puts a second code example in one card body
  will have it silently vanish from rendering -- worth a lint/warning in the eventual
  quality gate rather than only a silent frontend drop, so it's visible to whoever
  writes the card, not just to whoever reads it.
- `/dev/reset` is a real, unauthenticated-in-practice, destructive endpoint sitting on
  the same running API as everything else. Low risk while this is a local-only
  two-person project; a real risk if forgotten before any broader deployment.

## Revisit when

- docs/tasks/0006's real hero-planning mechanism gets built -- replace the seeder's
  "first card listed" placeholder and consider the DB constraint mentioned above.
- Before any deployment reachable outside localhost -- gate or remove `/dev/reset`.
