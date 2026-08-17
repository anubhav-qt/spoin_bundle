# ADR-0036: Topic discovery modal replaces the inline Discover list

- **Status:** Accepted
- **Date:** 2026-08-18
- **Deciders:** Anubhav

## Context

Today the right rail (ADR-0015) stacks four boxes: the topic filter chips (`TopicRail`),
per-topic progress (`TopicsProgressBox`), an inline top-5 Discover list (`DiscoverBox`),
and Request-a-topic (`RequestTopicBox`), in that order. Two problems this ADR addresses:

1. **Discover is capped at 5 rows inline** (`discover_topics` — `LIMIT 5`,
   `api/routers/topics.py`) with no way to see more without a bigger rail footprint. A
   proper browsing surface needs more room than a right-rail box can spare.
2. **A user's custom (self-requested) topics have no dedicated view.** Item 5 of this
   punch list added `GET /topics/custom`, returning each custom topic's most recent
   `GenerationJob.status` — but nothing in the UI surfaces it. A topic stuck mid-generation
   looks identical to a broken one from the client's side (this is also the likely
   explanation behind the separately-investigated `dsa`/Beginner-quiz confusion).

## Decision

**Replace the inline `DiscoverBox` list with a single "View all topics" entry point** in
the right rail, opening `TopicDiscoveryModal` — reusing the existing
`.modal-overlay`/`.modal-panel-wide` portal chrome ADR-0018's block-expand modal already
established, rather than inventing new modal chrome. The modal has two modes, switched by
a top toggle mirroring `ThemePicker`/filter-group's discrete-button pattern:

- **Discover** (default): the same Popular/For You data `DiscoverBox` showed, but with
  room to browse more than 5 rows and no per-row height pressure from the rail's narrow
  column.
- **Your custom topics**: calls `GET /topics/custom` and renders each of this user's
  self-requested topics with a status badge — Pending / Generating / Ready / Failed,
  mapped from `generation_status` — so "why can't I use this yet" has a direct, honest
  answer in the same surface where the topic was requested, instead of only discoverable
  by trying to take a quiz and hitting a 409.

**`RequestTopicBox` moves to sit directly below `TopicsProgressBox`** (the topic filter
box), ahead of the new "View all topics" entry point. Right rail order becomes:
`ThemePicker`/`FocusToggle` row → `TopicRail` → `TopicsProgressBox` → `RequestTopicBox` →
"View all topics" button. Rationale: typing a topic name is the fast path (no modal, no
browsing); it belongs immediately after "your topics," with discovery/browsing — the
slower, more deliberate action — demoted to an explicit modal entry rather than
competing for the same always-visible rail space.

**`DiscoverBox.tsx` itself is deleted**, not kept alongside the modal. Its list-rendering
logic (Popular/For You toggle, row, Follow button, opening `TopicStatsModal` per row) moves
into `TopicDiscoveryModal.tsx`'s Discover mode rather than being duplicated.

## Consequences

**Easier**
- Discover can show more than 5 topics without the right rail growing unboundedly.
- "Is my custom topic ready yet" has a real answer instead of silent failure at quiz time.
- One fewer always-visible right-rail box; the rail's vertical footprint shrinks.

**Harder**
- Discovering topics now costs an extra click (open the modal) versus always being
  visible inline. Accepted: browsing beyond 5 already implied wanting more space, and the
  action itself is now less contended for user attention against the always-important
  progress/filter boxes above it.
- The custom-topics status view polls nothing — it's a snapshot fetched on modal open. A
  `pending`/`running` topic won't visibly progress to `completed` without reopening the
  modal. Acceptable for now (ADR-0003: generation is minutes-to-hours on free tier, not
  something worth polling for); revisit if this becomes a common complaint.

## Alternatives considered

**Keep `DiscoverBox` inline and add a separate custom-topics box beneath it.** Rejected:
adds a fifth permanent rail box for a view most users check rarely (only relevant while a
custom topic is mid-generation), worse for rail density than folding it into the same
modal as a mode toggle.

**Poll `GET /topics/custom` while a job is pending/running, refreshing the badge live.**
Rejected for now — no other client-side polling loop exists in this codebase (feed/
progress are all refresh-on-event, not interval-polled), and free-tier generation
timescales (minutes-to-hours) make polling low-value relative to the complexity of adding
the first polling loop. Revisit if this pattern is needed elsewhere too.

## Revisit when

If a live "still generating…" progress indicator is requested for custom topics, revisit
the "no polling" call above — by then there may be enough demand across features to
justify a shared polling/websocket mechanism rather than one-off for this modal.
