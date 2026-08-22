# ADR-0052: A single-slot undo toast for removal in Notes/Liked/Saved

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** Anubhav

## Context

Removing a card from Notes, Liked, or Saved was already a one-click, no-confirmation
action -- consistent with those views' optimistic-update pattern (unlike/unbookmark/
delete-note all update local state immediately, before the server round-trip
resolves). Nothing softened an accidental removal. The request is an undo affordance:
a bottom toast, live for 5 seconds, dismissible early via an X.

Two things make this more than "add a toast":

1. **The three "remove" actions are not the same operation.** Unliking and
   unbookmarking are hard `DELETE`s of `CardLike`/`CardBookmark` rows
   ([engagement/service.py](../../apps/api/src/spoin/engagement/service.py)).
   Deleting a note is `DELETE /cards/{id}/note`. There is no shared "soft delete" or
   "trash" concept anywhere in this schema to lean on (CLAUDE.md is explicit that
   `spoin_db` has none, and inventing one for this alone would be a parallel
   mechanism for a five-second convenience).
2. **Every collection view stays mounted-but-hidden once visited**
   (`AppShell`'s `visited` set, `hidden` attribute, never unmounted) so switching
   from Liked to Notes mid-countdown must not lose the toast. A toast owned by the
   view that triggered it would disappear the moment its subtree goes `hidden`.

## Decision

**Delete immediately; undo re-creates, it does not un-delete.** Each view captures
the full row it's about to drop from its own already-in-memory `rows` state, filters
it out (unchanged optimistic-update behavior), and hands the captured row to
`offerUndo()`. Undo re-issues the *original* mutating call -- `engagement.record(id,
"like")`, `engagement.record(id, "bookmark")`, or `api.saveNote(id, body)` -- and
re-inserts the row into local state. No new "pending delete" state, no deferred
write: the row is genuinely gone and genuinely restorable, the same way a real user
action would redo it.

**The honest cost this accepts: undo is a fresh row, not a reversal.** A re-liked
card gets a new `CardLike.created_at`; a restored note gets a new `updated_at`. Both
surface in "RECENT" sort order jumping the item to the top. This was chosen over
inventing soft-delete specifically to avoid a second schema concept for a UI
convenience -- see Alternatives.

**One undo slot, newest wins -- `lib/undo.ts`, a module-level store mirroring
`lib/refresh.ts`'s pub/sub shape** (this codebase's existing pattern for
"one piece of client state several disconnected components need to see and react
to"). `offerUndo()` replaces whatever offer is currently live and restarts its
5-second timer; there is no queue. Removing a second card while the first's toast is
still showing makes the first item permanently gone -- deliberately, matching how
Gmail's archive/delete toast behaves, rather than turning a lightweight affordance
into a list the user has to triage.

**One toast component, mounted once in `AppShell`, outside every view's subtree.**
`UndoToast` subscribes to the store and renders fixed-position, bottom-center,
`z-index: 120` (above the Saved-card overlay's `z-index: 100`, below the custom
cursor's `999`). This is what makes "switch views mid-countdown, toast survives"
work at all -- a toast rendered inside `LikedView`'s own tree would vanish under
`hidden` the instant the user navigates away.

**The X dismisses; it does not undo.** Clicking it calls `dismissUndo()`, which
clears the timer and the slot -- the removal already happened and stays that way.
This is worth stating because "X" on a toast is occasionally misread as "cancel the
action" rather than "stop offering to reverse it."

**`role="status"` / `aria-live="polite"`, not a focus-stealing dialog.** The toast
announces itself to assistive tech without interrupting whatever the user is doing,
consistent with how `GuestNotice` (the only other standing toast-like surface) is
built.

## Consequences

**Easier**
- Every "remove" action across the three views gets undo with the same ~15-line
  shape: capture row → filter → `offerUndo`. No new API endpoints, no schema
  changes.
- The store is view-agnostic; extending undo to the feed's like/bookmark toggle or
  to unfollowing a topic later is a call to `offerUndo`, not new infrastructure.

**Harder**
- `accent_hue`-style "one true value" reasoning doesn't apply here: the event log
  now honestly contains like → unlike → like sequences from a single accidental tap
  + undo, which is correct under ADR-0011's event/state/aggregate separation but is
  a fact worth knowing before reading engagement events as literal user intent.
- A 5-second window is short for a screen-reader or keyboard user to react to a live
  region and act before it disappears (WCAG 2.2.1 is stricter than this). Accepted
  because the removal is already committed -- the timeout only withdraws a
  convenience, it never destroys data outright, and the requested behavior was
  explicit about the 5-second figure.
- Restoring a row inserts it at the front of the client's in-memory list rather than
  recomputing where the active sort (`recent`/`oldest`/`topic`/`difficulty`) would
  actually place it -- all three sorts are server-side (`api.likedCards`/
  `savedCards`/`listNotes` take the sort key), so an exact client-side re-sort would
  duplicate that logic. The next natural refetch (the same `invalidate()` call each
  original removal already triggers) corrects the position.

## Alternatives considered

**A real soft-delete / trash table**, restorable without a new write. Rejected:
introduces a schema concept (`deleted_at` or a trash table) that nothing else in
this codebase has, for a five-second UI convenience -- the kind of thing CLAUDE.md's
"anything that must be *true* is enforced outside the model" framing would call
over-engineering in the other direction: adding a durable mechanism for a transient
UI state.

**Deferring the actual `DELETE`/`unlike` call until the 5 seconds elapse**, so undo
is simply "never send it." Rejected: `unlike`/`unbookmark` are in
`engagement.ts`'s `URGENT` set specifically because progression-adjacent state
should not sit unflushed client-side; a 5-second hold before *any* write would
invert that guarantee, and the row would need to be faked as already-removed in the
UI regardless, so nothing about this decision gets simpler.

**A toast queue** instead of a single replaced slot. Rejected: turns "quick
convenience if you misclick" into a small triage UI for anyone removing several
things in a row, which is the more common case (batch-cleaning Saved) this feature
is least useful for anyway.

## Revisit when

- If undo is wanted for the feed's own like/bookmark toggle, or for unfollowing a
  topic, `offerUndo`/`UndoToast` already generalize -- no redesign needed, just a
  new call site.
- If the 5-second window turns out to be a real accessibility complaint in practice
  (not hypothetical), lengthen it or pause the timer on focus/hover before reaching
  for a queue or a differently-shaped affordance.
