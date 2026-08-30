# Task 0034: Unify SavedView / NotesView / LikedView behind one shared shell (F6 rework)

**Owner:** unassigned
**Blocked on:** a `/design` pass and a superseding ADR (see below)

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

## Why it isn't just "do it"

[ADR-0046](../adr/0046-one-collection-surface.md) already considered extracting shared
React components (`<CollectionHeader>`, `<CollectionControls>`) and **rejected it "for
now"**: the three pages genuinely differ in *what* they put in the masthead and
controls and only agree on *how it looks*, so it shared the `.collection-*` **CSS
layer** instead. Its "Revisit when" names the trigger: *"The masthead/controls props
stop differing per page — that is the signal to promote the CSS layer into shared
components."*

So this task must:

1. Establish that the convergence trigger is actually met (or accept that it isn't and
   do a lighter drift-cleanup instead — dedupe helpers, align the undo wiring, fix the
   remaining `"SAVED CARDS"` / `"Search saved cards…"` microcopy — without a shared
   component).
2. Go through `/design` for the unified view and get owner confirmation (Phase 2.5 of
   the v1 plan lists "the unified collection view (F6)" explicitly).
3. Get a **superseding/amending ADR** (next free number) that points back to ADR-0046
   and that ADR-0046 points forward to.

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
