# ADR-0062: Daily goal ring, and "today" means the reader's local day

- **Status:** Accepted
- **Date:** 2026-08-23
- **Deciders:** mayanks0ni

## Context

`daily_card_goal` has existed on `app_user` since the settings surface shipped
(ADR-0045) — settable, but displayed nowhere. The request is a small circular
progress indicator in the right rail's utility strip (alongside the theme/font
pickers and focus toggle) showing today's cards-read against that goal, with the
detail reachable on hover or click rather than occupying permanent rail space.

Two things needed a real answer before this could be more than a component:

**What counts as "a card read."** The existing profile-stats query
(`ProfileService.get_profile_stats`) counted `engagement_event` *rows*, not
distinct cards. A card that trips the dwell threshold and then gets an explicit
"Got it" tap writes two completion events (`dwell_complete` then
`explicit_complete`) for the same card — `_mark_seen` doesn't suppress the second
one, and there's no reason it should, since the event log is the source of truth
and is supposed to record what happened, not deduplicate it (ADR-0011). Reading
that log with `COUNT(*)` was already silently over-counting the contribution grid
and `total_cards_read`; a new ring built the same way would inherit the bug rather
than surface it.

**What day it is.** Every existing date boundary in this codebase
(`get_profile_stats`'s monthly query, the streak CTE) truncates `occurred_at` in
UTC. For a reader outside UTC that makes "today" reset at a time with no relation
to their actual midnight — 5:30am for IST, for instance — so a card read at
11pm local time would count toward what the ring calls "yesterday."

## Decision

**Fix the count everywhere: `COUNT(DISTINCT card_id)`, not `COUNT(*)`/`COUNT(id)`.**
Applied to `get_profile_stats`'s totals and monthly-activity queries as well as
the new endpoint, in the same change — shipping a ring that disagrees with the
profile page it sits next to over what "reading a card" means would be worse than
leaving the bug alone.

**"Today" is the CLIENT's local day, computed server-side from a client-supplied
offset — not UTC, and not a server guess.** The client sends
`tz_offset_minutes` (`-Date.prototype.getTimezoneOffset()` — the sign flip
because that browser API returns UTC-minus-local, and this wants local-minus-UTC)
on every call to the new endpoint. The server adds that offset to the current UTC
instant, truncates to the local calendar day, then converts the resulting
midnight-to-midnight window back to a UTC range to query with
(`profile/service.py`'s `get_today_progress`). This keeps the query itself a plain
indexed `occurred_at >= / <` range scan — no per-row timezone conversion in SQL —
at the cost of trusting the client's clock/offset, which is an acceptable trade
for a personal-progress indicator with no server-side consequence if it's wrong
(nothing gates on this count; it only renders a ring).

**Scope: the ring only. The contribution grid and streaks stay on UTC.**
Extending local-day semantics to `get_profile_stats` would mean the month picker,
the streak CTE, and the heatmap all need the same offset threading, and streak
"consecutive day" logic gets meaningfully trickier once the day boundary moves —
worth doing, not worth doing as a side effect of a progress ring. This means the
codebase now has two different definitions of "a day" (the ring: local; the
profile page: UTC) until that follow-up happens. Documented here specifically so
that gap isn't rediscovered as a mystery.

**New endpoint, not a reuse of `/profile/me/stats`.** That endpoint computes a
full month of daily buckets plus a recursive streak CTE — correct for a monthly
view opened occasionally, wasteful for a single count that refetches every time a
card is marked read (piggybacking on the same `engagement.whenIdle()` signal
`AppShell` already uses to refresh per-topic progress, `AppShell.tsx`'s
`onCardSeen`). `GET /profile/me/today` is one indexed `COUNT(DISTINCT card_id)`
over a bounded range, cheap enough to run that often.

**Component shape: hover reveals, click pins, matching `.share-popover`'s
existing pattern rather than inventing a second one.** `DailyGoalRing` renders an
inline-SVG ring (two `<circle>`s, `stroke-dasharray`/`stroke-dashoffset`) with an
anchored detail popover — same DOM shape as Card.tsx's share popover
(`.share-action-wrap` → `.share-popover`), reused via a second class
(`.share-popover.daily-goal-popover`) rather than a parallel set of popover
styles, only repositioned (below the trigger, right-anchored, since this sits at
the top of the rail rather than in a card's bottom action row). Click toggles a
pinned-open state independent of hover, so touch devices (no hover event at all)
and a deliberate look on desktop both work, dismissed by Escape or an outside
click — the same dismissal wiring the share popover already uses.

**Renders an empty track immediately, never a hidden/missing component.**
`AppShell` seeds `dailyGoal` state at `{cards_read: 0, goal: 10}` (the DB
default) rather than `null`, so the ring is present and correctly interactive
from first paint instead of popping in once the fetch resolves or needing an
extra loading-state branch in `RightRail`.

## Consequences

**Easier**
- A reader gets a persistent, low-footprint signal of daily progress without a
  new dedicated view — this was the first surface for `daily_card_goal` anywhere
  outside Settings.
- The `COUNT(DISTINCT card_id)` fix makes `total_cards_read` and the
  contribution grid honest for anyone who has ever both dwelled past and
  explicitly completed the same card.

**Harder**
- Two definitions of "today" now coexist (ring: local day; stats page: UTC day)
  until the profile page gets the same treatment — see Revisit below.
- The day boundary trusts the client's reported offset. A user who deliberately
  or accidentally misreports it (spoofed timezone, a stale service worker) sees
  a ring that resets at the wrong moment — low stakes (nothing is gated on it),
  but worth naming as the honest cost of not computing this server-side from a
  stored user preference instead.

## Alternatives considered

**Compute "today" in UTC, matching everything else.** Rejected: the whole point
of the ring is to tell a reader "you're done for today" or "N more to go" at a
glance; a boundary that doesn't correspond to their actual day defeats that,
and IST (a substantial fraction of the intended audience, per the existing
demand-driven pool-fill and topic curation choices elsewhere in this codebase)
sits far enough from UTC (+5:30) that the mismatch would be immediately
noticeable, not a rounding-error edge case.

**Store a `timezone` column on `app_user` instead of trusting a per-request
offset.** More correct in principle (survives a user changing devices/browsers
with different clocks) but a real schema addition, a new settings field, and a
migration for what's currently a single, low-stakes ring. `Date.prototype
.getTimezoneOffset()` is cheap, available on every request with no round trip,
and wrong in the same rare ways a stored value could also be stale in.

**A full progress bar or numeric readout always visible in the rail**, instead
of a ring that discloses on hover/click. Rejected per the request's own framing
("small circular progress bar ... on hover or click shows...") — a
permanently-expanded readout was explicitly not what was asked for, and would
cost more rail real estate for information that's useful to check, not stare at.

## Revisit when

- If the contribution grid or streak calculation is next touched for any other
  reason, fold local-day semantics in then rather than leaving the UTC/local
  split standing indefinitely.
- If per-device clock spoofing or DST-transition edge cases around the ring
  turn out to matter in practice (not hypothetically), move to a stored
  `timezone` preference instead of the per-request offset.
