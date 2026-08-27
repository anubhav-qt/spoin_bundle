# Task 0027: A mobile shell -- a floating pill nav, and the right rail becomes a topics sheet

**Owner:** mayanks0ni
**Status:** Reverted, then superseded -- the ADR-0063 implementation was rolled back to
the `3bc9c30` baseline with the rest of an in-flight UI branch. The mobile shell was
redesigned and re-landed under [ADR-0064](../adr/0064-mobile-shell-tab-bar.md) (edge-to-edge
tab bar instead of a floating pill); the right rail's own restyle is
[task 0028](0028-responsive-right-rail-and-controls.md).

## Goal

Below 1150px, `.rail-right` was `display: none`; below 680px, `.rail-left` was too. Every
theme/font picker, the topic filter, the daily goal ring, Notes/Liked/Saved/Profile/
Settings navigation, and log out were unreachable on a phone or narrow tablet -- there was
no other way in. Make the whole shell usable on a phone without a second component tree or
any JS viewport detection: `Sidebar` and `RightRail` stay the same two components, CSS
re-places them instead of hiding them.

A first pass shipped a full-width bottom bar with all six destinations, and duplicated
`RightRail`'s entire contents (theme/font/focus/goal, plus topics) into one sheet. Revised
before merging: a floating four-item pill (Home, Topics, Profile, Settings), with Notes/
Liked/Saved/log out moved under Profile (`MobileProfileNav`) and appearance controls
routed to `SettingsView`, which already owned that ground, instead of duplicating it.

## Non-goals

- Redesigning the feed, card, or modal content for mobile -- ADR-0021's ASCII column
  budget, code blocks' horizontal scroll, and `CustomCursor`'s `pointer: fine` gate already
  cover that ground; this task is the shell chrome around them.
- Auth/onboarding/share route polish beyond confirming they aren't broken by the shell
  change -- they're centered single-column layouts already, not part of the three-column
  grid this task touches.
- `HeroTutorialOverlay`'s callout positioning against the new pill -- deferred, see
  ADR-0063's "Not done" note.
- Rebuilding `SettingsView`'s appearance controls on mobile -- `MobileTopBar` surfaces the
  *live* controls (theme, focus, daily goal, refresh) that were already in `RightRail`'s
  top row; the full settings surface (palette picker, font picker, reduced motion, daily
  goal target, difficulty, topic management) stays exactly where it already was.

## Key architectural invariants

- No parallel mobile component tree, no `matchMedia`/`useMediaQuery` in React -- avoids
  duplicating `RightRail`'s fetch-on-mount children (`DiscoverBox`) and the SSR/hydration
  mismatch a client-only viewport check would introduce.
- `TopicRail` (rendered a second time for the mobile topic strip), `MobileTopBar`, and
  `MobileProfileNav` are all safe to duplicate/add because they're pure presentation, no
  fetch of their own -- `RightRail` is not, and stays a single instance toggled by
  `open`/`onClose`, never conditionally mounted.
- Settings owns settings. The mobile nav routes to existing surfaces (`SettingsView` via
  the pill's Settings item, `RightRail`'s topic tools via the Topics item) rather than
  growing a second copy of either.

## Files touched

- `apps/web/components/Sidebar.tsx` -- `.nav-items` wrapper; Notes/Liked/Saved marked
  `.nav-item-mobile-hidden`; new "Topics" nav item (`onOpenRail`, was a separate topbar
  trigger in the first pass); exports `VIEW_LABEL` for `MobileTopBar` to reuse.
- `apps/web/components/RightRail.tsx` -- `open`/`onClose` props, backdrop, close button,
  Escape + scroll-lock effects (mirrors `TopicDiscoveryModal`'s existing pattern);
  theme/font/focus/goal row wrapped in `.rail-appearance` so it can be hidden as a unit
  ≤680px, where `MobileTopBar` carries the live controls instead.
- `apps/web/components/MobileTopBar.tsx` (new) -- wordmark/dev-reset, `DailyGoalRing`,
  `FocusToggle`, Refresh. Fixed top bar, ≤680px only.
- `apps/web/components/MobileProfileNav.tsx` (new) -- Notes, Liked, Saved, log out/sign
  up. Rendered inside `ProfileView`, ≤680px only.
- `apps/web/components/ProfileView.tsx` -- new `onNavigate` prop, renders
  `MobileProfileNav`.
- `apps/web/components/AppShell.tsx` -- `railOpen` state, a second `TopicRail` instance in
  `.mobile-topic-strip`, `MobileTopBar` render (both hidden in focus mode), a shared
  `enterFocus` callback.
- `apps/web/components/icons.tsx` -- new `SlidersIcon` for the Topics nav item.
- `apps/web/app/globals.css` -- the ≤1150px sheet, the ≤680px pill/topbar/strip, and
  mobile overrides for `.undo-toast`/`.guest-notice`/`.focus-toggle[data-focused="true"]`
  so they clear the new fixed chrome.
- `apps/web/app/layout.tsx` -- `viewport.viewportFit: "cover"` for safe-area insets.

## Verification checklist

Not yet run against a live build -- this environment has no `apps/web/node_modules` and no
API venv (dependencies live in the user's Docker container), so neither `npm run typecheck`
nor a browser check was possible here. Before merging:

- [ ] `make check` / CI's `web` job (`npm run typecheck`, `npm run build`) passes.
- [ ] 375/390px (phone): the pill shows Home/Topics/Profile/Settings only; Profile shows
      Notes/Liked/Saved/log out below "Edit profile"; Topics opens the bottom sheet;
      `MobileTopBar`'s daily goal ring, focus toggle, and refresh all work; topic strip
      filters the feed with zero taps; Escape and backdrop-tap both close the sheet.
- [ ] 768/1024px (tablet): Topics opens a right-side slide-over instead of a bottom sheet;
      `Sidebar` still renders full-size with all six destinations + log out inline,
      unaffected by the mobile-only classes.
- [ ] 1280/1440px (desktop): pixel-identical to before this task -- pill, `MobileTopBar`,
      backdrop, and mobile topic strip are all `display: none`; `.rail-appearance` is
      visible inline as before.
- [ ] Focus mode on phone: `MobileTopBar` and the pill both disappear; the exit-focus
      button lands clear of the notch with no leftover topbar-height gap above it.
- [ ] iOS Safari specifically: notch/home-indicator clearance with the URL bar both shown
      and collapsed; confirm `.modal-panel`'s `84dvh` doesn't clip against the collapsed-bar
      viewport the way `84vh` did.
- [ ] `TopicDiscoveryModal` opened from inside the rail sheet (via "View all topics")
      stacks above the sheet, not behind it (z-index 91 sheet vs. 100 modal).
