# Task 0034: Extract one shared `CollectionView` from SavedView / NotesView / LikedView

**Owner:** unassigned
**Blocked on:** nothing

## DONE — 2026-08-31, `feat/v1-finish-line` (`3bf8373`)

`components/CollectionView.tsx` now owns the masthead, control bar, chip, rule,
state block, footer, `rowsRef` + `offerUndo` wiring, `skipNextRefreshRef` guard
and the server-authoritative `seen` merge. `LikedView` / `SavedView` /
`NotesView` are each a ~90-line `CollectionConfig` — labels, empty-state copy,
one `fetch`, and per-card props wired to shared `removeWithUndo` / `updateRow`
helpers. Notes keeps its client-side filter/sort via `clientFilterSort` +
`sortRow` + `searchExtra`. Dead `.saved-tile*` / `.saved-grid` / `.saved-overlay*`
/ `.saved-skeleton*` CSS swept (~290 lines); `.liked-*` / `.notes-*` list +
skeleton copies folded into `.collection-list` / `.collection-skeleton-*`. Net
-1441/+211 across the three views + globals.css. Verified live: all three render
with the right copy, and unlike / unbookmark / cleared-note each remove-with-undo
correctly. Microcopy note: Revisit keeps "SAVED CARD(S)" / "Search saved cards…"
(the *action* is still Save — F6); the undo label is "Removed from Revisit".

## Status (2026-08-30, `feat/v1-finish-line`)

**The visual unification is done.** [ADR-0072](../adr/0072-revisit-drops-its-bespoke-grid.md)
+ the `SavedView.tsx` rewrite dropped "Revisit"'s bespoke tile grid / overlay; it
now renders the same vertical `Card` list as Liked and Notes (shared
`.collection-*` chrome, new `.collection-list` class, same undo wiring). The
three views are near-identical React now.

**What's left is the code-dedup:** collapse the three near-mirror components into
one `CollectionView` parameterised by `{scope, eyebrow, title, emptyState,
engagementKind, store, initialProp, unProp}`. And the dead-CSS sweep below.

## The problem

`SavedView.tsx` (~519 lines), `NotesView.tsx` (~420) and `LikedView.tsx` (~388) have
visibly diverged despite doing the same job — a filtered, sortable, searchable list of
a user's collected cards with an undo-on-remove window. The three carry near-duplicate
copies of: topic filter chips, the empty / error / loading states, the search + sort
control row, the `rowsRef` mirror + `offerUndo` wiring, the `skipNextRefreshRef` guard,
and the server-authoritative `seen`-merge. The v1 finish-line plan (Phase 1 Wave 2, F6)
proposed extracting the shared shell into one `CollectionView` all three use.

The **"Saved" → "Revisit" rename half of F6 shipped** on `feat/v1-finish-line`
(commit `1b2cbf7`) — nav label + view eyebrow, copy only. This task is the rework half
only.

## Why it's now unblocked

[ADR-0046](../adr/0046-one-collection-surface.md) rejected extracting shared React
components "for now" because the three pages differed in *what* they put in the
masthead/controls. [ADR-0072](../adr/0072-revisit-drops-its-bespoke-grid.md) removed
the last structural difference (Saved's grid), so the trigger ADR-0046 named —
*"the masthead/controls props stop differing per page"* — is met. No further
`/design` pass or ADR is needed; this is now a straight refactor.

## Also: the dead-CSS sweep

`ADR-0072` left `.saved-tile*` / `.saved-overlay*` / `.saved-grid` /
`.saved-skeleton*` in `globals.css` — nothing renders those class names any more.
Remove them here (and fold `.liked-view-list` / `.notes-view-list` into
`.collection-list`).

## Constraints carried from F6's plan entry

- Keep the `saved` view key, `RefreshScope`, the `card_bookmark` table and every
  `api.saved*` name. The rename was user-facing copy only; the wire format is untouched.
- Saved's grid + card-overlay, Notes' inline note editing, and Liked's plain list are
  the page-specific vocabulary ADR-0046 says stays page-specific. A shared shell owns
  the masthead / controls / states / undo wiring; it does not flatten Saved's grid into
  a list.
- Medium risk: unifying three views means a regression lands in all three at once. Ship
  behind the review phase (Phase 3) so it sees the final shape.
- `make check` / `tsc --noEmit` green per commit.

## Also fold in

The leftover F6 microcopy the rename commit deliberately skipped because it was
entangled with pre-existing uncommitted Wave-1 changes to `SavedView.tsx`:
the `"N SAVED CARDS"` metadata line, the `"Search saved cards…"` placeholder / aria
label, the `"Removed from Saved"` undo-toast label, and the `SavedView` module
docstring's "bookshelf of saved knowledge cards" framing.
