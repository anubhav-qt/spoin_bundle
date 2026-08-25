# ADR-0061: A mobile shell -- a floating pill nav, and the right rail becomes a topics sheet

- **Status:** Accepted (amends [ADR-0013](0013-topic-relationship-graph.md)'s three-column
  shell as restructured by [ADR-0015](0015-topic-progress-and-discovery.md))
- **Date:** 2026-08-26
- **Deciders:** mayanks0ni

## Context

The three-column shell's breakpoint handling collapsed under its own weight rather than
adapting. `.rail-right` was `display: none` below 1150px, and `.rail-left` was
`display: none` below 680px -- with no other way in, everything either rail owns
(topic filtering, theme/font pickers, the daily goal ring, Notes/Liked/Saved/Profile/
Settings navigation, log out) was simply unreachable on a phone or a narrow tablet. The
≤680px block *did* still carry a half-finished `.rail-right` restyle (`position: static`,
trimmed padding) clearly meant to stack the rail below the feed -- dead code, since the
≤1150px rule's `display: none` wins first and nothing ever re-enabled it. Someone had
started this fix and the cascade quietly ate it.

Card content itself was already mobile-aware -- ADR-0021 budgets ASCII scenes to 40
columns explicitly because "a phone renders roughly 38-42 monospace columns," code blocks
scroll horizontally instead of wrapping, `CustomCursor` gates itself off `pointer: fine`.
The gap was the shell chrome, not the cards.

A first pass at this ADR shipped a full-width bottom bar with all six `Sidebar`
destinations plus log out, and duplicated `RightRail`'s entire contents (theme, font,
focus toggle, daily goal, topic filter, discovery) into one sheet reachable from a topbar
trigger. That duplicated ground `SettingsView` already owned -- its APPEARANCE section
already has the palette and font pickers, and its LEARNING section already has a "Topics
→ MANAGE" row that opens the same `TopicDiscoveryModal`. Revised before merging, per
direct product feedback, into the design below.

## Decision

**No parallel mobile component tree, and no viewport-detection JS.** `Sidebar` and
`RightRail` stay the same two components; CSS re-places them instead of hiding them, same
principle as the first pass. Two new presentational components (`MobileTopBar`,
`MobileProfileNav`) are added rather than growing `Sidebar`/`RightRail`'s own prop surface
indefinitely -- both are pure props, no fetch of their own, so rendering them is the same
"safe to duplicate" reasoning `TopicRail`'s second instance already relies on.

**The mobile nav is a floating pill, not a full-width bar, and it carries four items:**
Home, Topics, Profile, Settings. Concretely, below 680px:

- **`Sidebar`'s `.nav-items` becomes the pill's content.** Notes, Liked, and Saved get a
  `.nav-item-mobile-hidden` class and disappear from the pill (still full rows in the
  681-1150px tablet rail, unaffected); the "Deep Dive" stub and the log out/sign-up row
  disappear the same way. A new "Topics" button is inserted between Saved and Profile,
  using the same `SlidersIcon` the first pass put in the topbar -- it opens `RightRail`
  as a sheet, exactly as before, just relocated into the nav list so it has a real slot at
  every width: a normal labeled row 681-1150px, a pill item ≤680px, `display: none` above
  1150px where the rail is already inline.
- **Everything moved out of the pill lives under Profile instead**, via the new
  `MobileProfileNav` component rendered inside `ProfileView` just below "EDIT PROFILE":
  Notes, Liked, Saved, and log out/sign up (`useAuth`, same as `Sidebar`'s own). "Profile
  for everything in the left rail," per how it was asked for.
- **`.rail-left` itself shrinks to the pill's own box** -- centered, `width: auto`,
  floating `--mobile-pill-gap` above the bottom edge with a blur/shadow -- rather than
  spanning the viewport. `.nav-items` carries the actual pill chrome (background, border,
  border-radius, shadow); `.rail-left` is just a positioning wrapper now that its topbar
  and logout row are both hidden or gone.
- **Labels are icon-only-by-default globally (900px), re-enabled at small size just for
  the four pill items** (`.nav-items .nav-item-label`) -- a floating pill with no
  persistent text has no way to self-identify on a touch device, which has no hover state
  to reveal a label the way `.sidebar-refresh`'s desktop expand-on-hover pattern does.

**"Settings for everything which can be configured for this website" already existed --
this ADR routes to it instead of rebuilding it.** `RightRail`'s theme/font/focus-toggle/
daily-goal row moves into a new `.rail-appearance` wrapper, CSS-hidden ≤680px in favor of
a new fixed `MobileTopBar` (wordmark/dev-reset, `DailyGoalRing`, `FocusToggle`, Refresh) --
both are still just `RightRail`'s and `Sidebar`'s original controls, relocated, not
rebuilt. What's left in the sheet below 680px is purely topic filtering and discovery,
which is what makes "Topics" an honest name for the button that opens it. `SettingsView`
itself is untouched -- it was already the single place the palette, font, daily goal
target, difficulty, and topic management live; this ADR does not duplicate that ground a
second time on mobile.

- **Fixed-position elements that assumed no bars exist get pushed clear of them**:
  `.undo-toast`, `.guest-notice`, and `.focus-toggle[data-focused="true"]` each get a
  ≤680px override keyed off `--mobile-topbar-h` (still `MobileTopBar`'s height) and the
  new `--mobile-pill-h`/`--mobile-pill-gap` pair. `.focus-toggle[data-focused="true"]`
  (the exit-focus button) no longer needs topbar clearance at all -- `MobileTopBar` and the
  pill both unmount in focus mode, same as `Sidebar`/`RightRail` always have, so there is
  nothing left to dodge but the notch.
- **`viewport.viewportFit: "cover"`** (`app/layout.tsx`) plus `env(safe-area-inset-*)` on
  the fixed bars and the pill, so the iOS home indicator and notch don't overlap fixed
  content. `.modal-panel`'s `max-height` moved from `84vh` to `84dvh` -- `vh` resolves
  against the largest possible viewport, so it overshoots once Safari's URL bar is
  actually showing.

**Not done, explicitly deferred:** `HeroTutorialOverlay`'s callout positioning
(`getBoundingClientRect` against the hero card, in viewport coordinates) is unaffected by
the new bars in most cases, since it already measures live rather than assuming fixed
offsets -- but a hero card scrolled near the very bottom of the viewport can still have its
callout land under the pill. Fixing that needs the overlay to know the pill's height,
which it doesn't today. Small enough, and rare enough (first-run-only, hero-card-specific),
not to block this ADR on.

## Consequences

**Easier:** every destination `Sidebar`/`RightRail` already gate behind a click is now
reachable below 1150px, where before it was invisible with no way in. Filtering the feed
by topic goes from "open the sheet" to zero taps on a phone. Appearance/goal controls have
exactly one home on every width (`SettingsView` + `MobileTopBar`'s live controls) instead
of the first pass's two (`RightRail`'s sheet duplicating `SettingsView`).

**Harder:** the fixed-position inventory (toast, guest notice, focus toggle, and the
deferred hero-tutorial case above) is now something every *future* fixed-position addition
has to check against `--mobile-topbar-h`/`--mobile-pill-h`/`--mobile-pill-gap`, not just
these three. There is no lint or test that catches a new one landing at a hardcoded
`top`/`bottom` and drifting behind the pill or topbar -- this is a documented convention,
not an enforced one (see CLAUDE.md's "a hard architectural rule gets enforced twice" --
this one only got the doc half so far).

**Neutral:** `RightRail` picked up two props (`open`, `onClose`) it only meaningfully acts
on below 1150px; above that they're always `false`/unused because the trigger that would
set them is itself CSS-hidden. `ProfileView` picked up an `onNavigate` prop it only uses
≤680px, for the same reason.

## Alternatives considered

**A separate `MobileShell` component, switched on `useMediaQuery`.** Rejected --
duplicates `RightRail`'s fetch-on-mount children (`DiscoverBox`), needs its own
prop-drilling from `AppShell`, and introduces an SSR/hydration mismatch window (the
media query can't be known server-side, so the first paint would guess wrong on one
platform or the other). CSS re-placement has none of these problems and needs zero new
state beyond `railOpen`.

**A full-width bottom bar with all six destinations plus log out (the first pass).**
Rejected on direct feedback: seven targets at the 44px minimum does fit, but it also means
the bar competes with the feed for attention on every screen instead of receding, and it
gave the sheet no clear identity ("filters and settings," vaguely) once it also carried
appearance controls. A four-item pill that recedes over the feed and a sheet that is
honestly just "Topics" both read as more deliberate.

**Duplicate `SettingsView`'s theme/font/goal controls into the rail sheet (the first
pass's actual behavior).** Rejected once `SettingsView`'s existing APPEARANCE/LEARNING
sections were checked -- they already own this ground (`ThemePicker`, `FontPicker`, the
daily goal target, and a "Topics → MANAGE" row opening the same `TopicDiscoveryModal` the
rail's "View all topics" does). Duplicating it into a second surface means two places to
keep in sync and two different interaction models for the same setting depending on
screen width, for no benefit over "Settings owns settings."

**Squeeze `.rail-left` down to a narrow icon column all the way to phone widths**, instead
of a floating pill at 680px. The ≤900px icon-only column already works fine down to 681px
width-wise. Rejected for phones specifically because a persistent icon column eats
horizontal budget a bottom nav doesn't, and a floating pill is closer to the platform-
native pattern on a touch device -- reachable one-handed and visually recedes over content,
which a 72px vertical rail pinned to one edge does neither.

## Revisit when

- A fixed-position element is added anywhere in `globals.css` -- check it against
  `--mobile-topbar-h`/`--mobile-pill-h`/`--mobile-pill-gap` before it ships, per the
  "harder" consequence above.
- `HeroTutorialOverlay`'s callout is confirmed to actually land under the pill in practice
  (deferred case above) -- pass `--mobile-pill-h` + `--mobile-pill-gap` into its bounds
  calculation.
- If usage ever suggests Notes/Liked/Saved are frequent enough on mobile to want zero-tap
  access instead of "Profile, then tap again," reconsider a fifth pill slot or a swipe
  gesture instead of routing them all through Profile.
