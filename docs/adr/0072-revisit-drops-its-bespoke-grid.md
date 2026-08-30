# ADR-0072: The "Revisit" collection uses the same list as Liked and Notes

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Anubhav
- **Amends:** [ADR-0046](0046-one-collection-surface.md) — which listed "Saved's
  tile grid and overlay" as page-specific vocabulary to keep. That line no
  longer holds; the rest of ADR-0046 (the shared `.collection-*` CSS layer, the
  shell owning the gutter) stands unchanged.

## Context

The three collection pages — Liked, Notes, and Saved (renamed "Revisit" in F6)
— already share the `.collection-*` masthead, search, sort pills and topic
filter chips (ADR-0046). Below that shared chrome they diverged: Liked and Notes
render a **vertical list of full `Card` components**; Saved rendered a bespoke
**2-column tile grid** where each tile was a compact preview that opened the
full card in a **portal overlay** ("pull a book off the shelf").

Looking at the running app, that distinction wasn't earning its complexity.
Liked and Notes are visually identical and read as one surface; Saved was the
odd one out for no product reason a reader would notice or want. The tile grid
was ~150 lines of `SavedView.tsx` (`SavedTile`, `SavedCardOverlay`, seen-state
plumbing duplicated for the overlay) and ~200 lines of `.saved-tile*` /
`.saved-overlay*` / `.saved-grid` CSS, all of it a second implementation of
"show the user their collected cards".

## Decision

**"Revisit" renders the same vertical `Card` list as Liked and Notes.**
`SavedView.tsx` is now a near-mirror of `LikedView.tsx` — same masthead, search,
sort, topic filter, `AnimatePresence` list, undo wiring — with bookmark
semantics (`initialBookmarked` / `onUnbookmarked`, `bookmarkedStore`,
`engagement.record(id, "bookmark")`) in place of like semantics. The tile grid,
the `SavedTile` component and the `SavedCardOverlay` portal are gone.

The card list uses a new shared `.collection-list` class (identical to the
byte-equivalent `.liked-view-list` / `.notes-view-list`, which
[task 0034](../tasks/0034-collectionview-rework-saved-notes-liked.md) folds in
when it extracts a shared `CollectionView`).

The `saved` view key, `RefreshScope`, the `card_bookmark` table and every
`api.saved*` name are untouched — this is presentation only.

## Consequences

**Easier**

- One list implementation to reason about instead of two. A change to how a
  collection presents cards is now the same change in all three views (and,
  after task 0034, one component).
- ADR-0046's "Revisit when: the masthead/controls props stop differing per
  page" condition is now materially met — the three pages differ only in copy
  and engagement kind, which makes the shared-component extraction (task 0034)
  low-risk.
- `SavedView.tsx` dropped from ~519 lines to ~300.

**Harder**

- The "browsable library at a glance" reading of the grid is gone. If a dense,
  scannable overview of a large saved collection turns out to be genuinely
  wanted, it comes back as a *view toggle* on the shared list, not a bespoke
  third layout.
- The `.saved-tile*` / `.saved-overlay*` / `.saved-grid` CSS is now dead code
  still sitting in `globals.css`. Left in place for this change (that file
  carries other in-flight edits); task 0034 removes it.

**Committed to**

- No collection page gets a bespoke card-list layout again. Structural
  differences between the three, if any are ever wanted, are options on the
  shared surface.

## Alternatives considered

**Keep the grid, unify only the chrome.** The status quo after F6's rename —
shared `.collection-*` masthead, bespoke grid body. Rejected: the grid was the
whole reason `SavedView` was 130 lines longer than its siblings and the reason
they'd diverge again, and nobody wanted the grid enough to defend it.

**Make the grid the shared layout for all three.** Liked and Notes become tile
grids too. Rejected: the full-card vertical list is the better default for
reading (you can act on a card without a modal), and Notes in particular needs
the inline note editor visible, which a compact tile can't show.

**Do the full `CollectionView` component extraction now, in this change.**
Rejected as scope: it touches `LikedView` / `NotesView` / `AppShell`, all of
which carry unrelated in-flight edits. Making the three views identical *first*
(this ADR) is the precondition that makes that extraction safe — it's tracked
as task 0034 with its own review.

## Revisit when

- A user with a large saved collection asks for a denser overview — then add a
  list/grid toggle to the shared `CollectionView`, don't fork the view.
- Task 0034 lands — at which point `SavedView` / `LikedView` / `NotesView`
  become one component and this ADR's "near-mirror" phrasing is obsolete.
