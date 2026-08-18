# ADR-0039: Remove swipe-to-dismiss; cards are not draggable

- **Status:** Accepted
- **Supersedes:** part of [ADR-0017](0017-card-archetypes.md) -- the swipe-right
  gesture and Framer Motion's `drag="x"` on `.node`. The rest of ADR-0017
  (archetype-based rendering, hybrid disclosure, `layout` animation) stands.
- **Date:** 2026-08-18
- **Deciders:** Anubhav

## Context

ADR-0017 added swipe-right as an alternate gesture for "mark seen," reusing Framer
Motion's `drag` API for a free FLIP-friendly dismiss animation. Its own "Alternatives
considered" section flagged the risk up front: swipe removing a card from view while
tapping the checkmark does not is "an inconsistency a user has to learn." In practice
it reads as accidental horizontal drag noise during normal scrolling/reading rather
than a discoverable gesture -- direct user feedback: "remove the swipe functionality
to mark as got it, its annoying," followed by "the cards should not be swipeable
either left or right, even a little bit."

## Decision

`motion.div` in `Card.tsx` no longer takes `drag`, `dragDirectionLock`,
`dragConstraints`, `dragElastic`, `onDragStart`, or `onDragEnd`. Cards do not move
under a pointer at all, not even the small elastic give the old `dragElastic`
allowed. "Got it" (tap) is the only way to mark a card seen from the card itself;
`explicit_complete` no longer has a swipe-triggered code path.

`onDismiss` / the `dismissed` card-visibility set in `Feed.tsx` are removed
entirely, not just disconnected -- swipe was their only caller, so keeping the
plumbing around would be dead code pretending to be a feature.

## Consequences

Easier: no drag/tap gesture-priority bugs (the `dragging` ref existed purely to stop
a post-drag synthetic click from also toggling the card), one less gesture to explain
in onboarding, no elastic-drag jank during normal scroll.

Harder / lost: no quick single-gesture "mark and remove from view" -- "Got it" now
always leaves the card in place (which was already true for the checkmark path, so
this makes the two mark-seen surfaces consistent instead of divergent, matching the
risk ADR-0017 named but didn't act on at the time).

## Alternatives considered

- **Keep swipe but raise the dismiss threshold / dampen `dragElastic`.** Rejected --
  the complaint was the gesture existing at all ("even a little bit"), not the
  threshold being too sensitive.
- **Keep `drag` for a subtle affordance but no-op `onDragEnd`.** Rejected -- a card
  that still visibly slides under a finger and then snaps back is the exact
  "annoying" behavior being removed, just without the dismiss consequence.

## Revisit when

A future request specifically asks for a gesture-based dismiss/archive action again
-- at that point, design it as its own visible, discoverable affordance rather than
reviving the implicit checkmark-alias gesture this ADR removes.
