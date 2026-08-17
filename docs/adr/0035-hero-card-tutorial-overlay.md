# ADR-0035: First-time hero-card tutorial overlay; no new SEEN mechanism needed

- **Status:** Accepted
- **Date:** 2026-08-18
- **Deciders:** Anubhav

## Context

The punch list item that prompted this asked for two things: (1) hero cards need "their
own explicit way to mark 'Got it'", since ADR-0018's hero cards render permanently
expanded and skip the normal collapse/expand state machine SEEN-marking is described
against in content-model.md; and (2) a one-time guided-tour overlay pointing new users at
that control.

**Investigation before building (1):** `Card.tsx:85-91` initializes `expanded` and
`everExpanded` to `true` whenever `isHero` — hero cards start in the same state a normal
card only reaches *after* being opened once. The mark-as-read control
(`.action-gotit`, `Card.tsx:439-448`) is gated on `disabled={!everExpanded}`, and since
that's already `true` for a hero card at mount, **the control is already live and
functional for hero cards today** — `gotIt()` (`Card.tsx:263-271`) is generic over hero
and non-hero. There is no missing mechanism to build here; ADR-0011's SEEN semantics
already covers hero cards correctly because "expanded" is trivially true for them, not
because of any hero-specific code path. This ADR exists for part (2) only.

## Decision

**Part (1): no change.** The existing `.action-gotit` button is the hero card's
mark-as-read control. Confirmed by reading, not assumed — see Context.

**Part (2): a spotlight overlay, shown once per browser, targeting the real DOM button.**

- **Trigger:** the first time a hero card renders for a user who hasn't dismissed the
  tutorial before (`localStorage["spoin-hero-tutorial-seen"]`, following the same
  per-browser persistence precedent as `ThemePicker`'s `spoin-palette` key — no server
  round trip, no `User` column). Checked once in `Card.tsx` per hero card mount; the first
  hero card to mount while the flag is unset shows it, every hero card after that
  (including hero cards mounted later in the same session, once the flag flips) does not.
- **Mechanism:** four fixed-position dimming strips (top/bottom/left/right) surrounding a
  rectangular cutout sized to the real `.action-gotit` button's live
  `getBoundingClientRect()`, recomputed on scroll/resize so the highlight tracks the
  button if the page moves under it. No new element sits on top of the button itself —
  the "hole" is a true gap in the overlay's DOM, not a `pointer-events: none` region, so a
  click that lands there reaches the real button underneath and fires its real `onClick`
  unmodified. This is what makes "clicking the actual control both dismisses the tutorial
  and marks the card read" fall out for free: it *is* the control, not a copy of it. A
  small arrow + label ("Tap here to mark this card as read") renders inside the nearest
  strip, pointing at the cutout.
- **Swallowed dismissal:** a click on any of the four strips calls
  `stopPropagation`/`preventDefault`, sets the localStorage flag, and unmounts the
  overlay — the click never reaches whatever was underneath that strip. This is standard
  event handling, not a hack: the strips are real, opaque, topmost elements over
  everything except the cutout.
- **Auto-dismiss on completion:** the overlay's visibility is `showTutorial && !seen` —
  so if the card gets marked seen through *any* path (the button itself, a swipe-right on
  a hero card if that ever changes, though today hero disables drag) while the tutorial is
  showing, the overlay disappears without a separate dismiss click. Only the direct-click
  path also flips the "seen" localStorage flag inside the button's own click handler,
  since only that path is a deliberate dismissal decision rather than an incidental one.

## Consequences

**Easier**
- No new backend state, no new engagement event kind, no schema change — everything here
  is presentational, client-only, and reversible by clearing localStorage.
- Reuses a DOM-hole spotlight pattern that generalizes to any future "point at this real
  control" tutorial without inventing a second approach.

**Harder**
- The overlay's cutout tracks one specific button's bounding rect at overlay-mount time
  plus scroll/resize — a layout change to `.action-gotit` (resize, reposition within the
  action row) needs no overlay-side change since the rect is read live, but a future
  redesign that removes or renames that control silently orphans the tutorial's target
  unless someone remembers to check this ADR.
- Per-browser, not per-account: clearing localStorage, or the same user on a second
  device/browser, sees the tutorial again. Accepted as consistent with the existing
  palette-picker precedent this follows, not a new gap.

## Alternatives considered

**A dedicated `User.hero_tutorial_seen` column.** Rejected: this is presentation-layer
state with no product consequence if lost or duplicated across devices — exactly the
kind of thing ADR-0023/ThemePicker already established localStorage as the right tier
for, and a DB column would be the only server-state write in the entire feature.

**A generic tour/onboarding library.** Rejected as overkill for a single-step,
single-target callout with no multi-step sequencing need. Revisit if a second guided
step is ever requested.

## Revisit when

If a second onboarding callout is requested elsewhere in the app, this overlay's
strip-and-cutout implementation should be generalized into a shared component rather
than copy-pasted, at which point a small library becomes the right call instead of the
alternative rejected above.
