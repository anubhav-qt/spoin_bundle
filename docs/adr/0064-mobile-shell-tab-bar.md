# ADR-0064: Mobile shell, take two -- an edge-to-edge tab bar and a Browse sheet

- **Status:** Accepted (supersedes [ADR-0063](0063-mobile-shell.md); amends
  [ADR-0013](0013-topic-relationship-graph.md)/[ADR-0015](0015-topic-progress-and-discovery.md)'s
  three-column shell)
- **Date:** 2026-08-27
- **Deciders:** magicalfizz

## Context

[ADR-0063](0063-mobile-shell.md) solved the right problem -- below 1150px the right rail
was `display: none` and below 680px the left rail was too, so topic filtering, the
theme/font pickers, the daily-goal ring, and half the navigation were simply unreachable
on a phone. Its implementation (a floating four-item pill: Home/Topics/Profile/Settings,
with Notes/Liked/Saved relocated under Profile via `MobileProfileNav`, and appearance
controls routed to `SettingsView`) was **reverted to the `3bc9c30` baseline** along with
the rest of an in-flight UI branch. ADR-0063's doc was left behind, describing code that
is no longer in the tree.

Rather than re-land ADR-0063 verbatim, the mobile view was redesigned from scratch this
session (the "Spoin Responsive and Mobile App" design canvas). The end goal is stated
plainly: **this ships as an app**, so the phone view should read like a native app, not a
website that collapsed. Three nav directions were sketched -- a floating pill (ADR-0063's
shape), an edge-to-edge tab bar, and a pill-plus-raised-action -- and the edge-to-edge tab
bar was chosen.

## Decision

Same core principle as ADR-0063, kept: **no parallel mobile component tree, no
`matchMedia` in React.** `Sidebar` and `RightRail` stay single components; CSS re-places
them by breakpoint. New components are pure presentation with no fetch of their own, so
adding them is the same "safe to duplicate" reasoning `TopicRail`'s second instance
already relies on.

### The breakpoint ladder

| Width       | Left nav                | Centre thread | Right rail                        |
| ----------- | ----------------------- | ------------- | --------------------------------- |
| `>=1401`    | `Sidebar`, hugs thread  | 640px         | `RightRail`, 350px                |
| `1151-1400` | `Sidebar`, narrower     | ~500px        | `RightRail`, ~300px               |
| `1101-1150` | `Sidebar`, narrower     | fluid         | `RightRail`, ~284px               |
| `681-1100`  | **gone** -> `MobileNav` | fluid         | `RightRail`, 250px (still inline) |
| `<=680`     | **gone** -> `MobileNav` | full width    | **gone** -> Browse sheet          |

> **Amended (later, same branch):** the `MobileNav` cut-over moved from `<=900` up to
> `<=1100`. The 3-column shell gets visibly cramped below ~1120px (right rail chips
> clipping, thread too narrow beside two rails), so the left nav folds into `MobileNav`
> there instead. The `681-900` / `901-1150` rows above are now `681-1100` / `1101-1150`;
> nothing else about the shell changed.

- **`.rail-left` hugs the thread.** The two side grid tracks are equal (350px) so the
  thread sits dead-centre in the viewport; the nav is `width: 212px; justify-self: end`
  inside its track. The nav labels are short -- this reclaims the far-left whitespace
  without moving the thread. (Replaces ADR-0063's untouched `275px` track.)
- **`MobileNav` (new, `<=1100px` -- see the amendment note above; originally `<=900px`)**
  is an **edge-to-edge tab bar** fixed to the bottom
  edge, five items: **Liked - Revisit - Home - Notes - Profile**, Home centred, the
  current item in `--accent` with its icon filled. Full-width, labels always shown, big
  touch targets, `env(safe-area-inset-bottom)` padding -- it reads like a native tab bar,
  which a floating pill with hidden labels does not. It carries navigation only.
- **"Revisit" routes to the Saved view** with a "Revisit" label for now. A real
  spaced-repetition re-read surface is [task 0015](../tasks/0015-topic-mastery-and-retention-mode.md),
  not built; the label is a deliberate placeholder pointing at where that feature will
  live, chosen over "Saved" so the eventual surface has a home already.
- **`MobileTopBar` (new, `<=680px` only)** -- wordmark/dev-reset, a Refresh control, the
  **Browse** button (`SlidersIcon`), and `DailyGoalRing`. Sticky at the top; the feed
  paints under it and the sticky `.station` labels stack below it. The `681-1100px` band
  keeps the right rail inline, so it does **not** render this bar.
- **`DailyGoalRing` is re-landed per [ADR-0062](0062-daily-goal-ring-and-local-day-semantics.md)**,
  not reinvented: `AppShell` seeds `dailyGoal` at `{cards_read: 0, goal: 10}`, fetches
  `GET /profile/me/today?tz_offset_minutes=...` (the API endpoint survived the revert) on
  mount and on every card-seen via the existing `engagement.whenIdle()` signal, and the
  ring keeps ADR-0062's hover-reveal / click-pin popover. The right rail's own copy of the
  ring is [task 0028](../tasks/0028-responsive-right-rail-and-controls.md).
- **The Browse sheet (`<=680px`)** is a second `RightRail` instance rendered with
  `variant="sheet"` -- a `document.body` portal, backdrop, drag grip, Escape +
  body-scroll-lock (the `TopicDiscoveryModal` idiom). It holds everything the docked rail
  holds: **Appearance (the `ThemePicker` swatch grid + `FontPicker`)**, the topic filter,
  "View all topics", "Your topics" progress, Discover, and a Settings shortcut.

### Where this departs from ADR-0063

- **Nav shape:** edge-to-edge tab bar, not a floating pill. Five destinations, not four.
- **Notes/Liked stay first-class** -- tab-bar items, not rows buried under Profile. There
  is no `MobileProfileNav`.
- **Appearance stays in the Browse sheet**, not routed to `SettingsView`. The user wants
  the theme swatch grid reachable in one place on mobile without a detour through
  Settings; `SettingsView` keeps its own appearance section as the full surface (palette
  picker, font list, reduced motion, daily-goal target), unchanged.
- **Settings is not a tab.** It is a shortcut at the foot of the Browse sheet.

### Hygiene re-landed from ADR-0063

The reverted branch's fixed-element fixes were sound and are restored: `viewport.viewportFit:
"cover"` in `app/layout.tsx`; `env(safe-area-inset-*)` on every fixed bar; `<=680px`
overrides pushing `.guest-notice` below the top bar and `.undo-toast` above the tab bar;
the sheet's `max-height` in `dvh`, not `vh`.

### Not in this ADR -- deferred to [task 0028](../tasks/0028-responsive-right-rail-and-controls.md)

The desktop/laptop/tablet right rail's own restructure from the same design canvas --
row 1 becoming `DailyGoalRing` + equal-width Theme/Font dropdown controls + Focus, and the
"Your topics" / "Discover" restyle -- is a separate change against shared components used
at three widths. The "Popular / For You" Discover toggle needs a `DiscoverBox` API
parameter that does not exist ([task 0003](../tasks/0003-personalized-topic-recommendations.md))
and is not shipped as dead UI.

## Consequences

**Easier:** every rail destination is reachable at every width, and the phone view is a
tab-bar app, not a shrunk desktop. Filtering by topic on a phone is one tap into the
Browse sheet, same as ADR-0063. The daily-goal ring is visible without opening anything.

**Harder:** the fixed-position inventory (`.undo-toast`, `.guest-notice`,
`.focus-toggle[data-focused]`) now has to be checked against the mobile bars' heights on
every future addition -- a documented convention, not an enforced one, same caveat
ADR-0063 already carried. Two `RightRail` render paths (rail / sheet) share one component,
so a change to its contents has to be sanity-checked in both. The "today" split ADR-0062
already documented (ring = local day, profile page = UTC) is unchanged and still open.

## Alternatives considered

- **Re-land ADR-0063's floating pill unchanged.** Rejected: the redesign this session
  deliberately picked the tab bar over the pill after sketching both. A pill with
  hidden-until-active labels has no way to self-identify on a touch device, and four
  destinations forced Notes/Liked/Saved into a Profile submenu that made them feel
  second-class.
- **Keep appearance controls in `SettingsView` only (ADR-0063's routing).** Rejected per
  direct product direction: the theme swatch grid should be one tap from the feed on
  mobile, in the same sheet as the topic filter, not two taps through a Settings screen.
- **Build a real Revisit view now.** Rejected: that is [task 0015](../tasks/0015-topic-mastery-and-retention-mode.md),
  which needs a scheduling ADR and a schema change first. The tab label is the cheap part.

## Revisit when

- [Task 0015](../tasks/0015-topic-mastery-and-retention-mode.md) ships -- the "Revisit"
  tab stops being a Saved-view alias and points at the real retention surface.
- Real usage shows the five-tab bar is one too many for a 320px screen -- fold Notes or
  Liked back toward Profile, the way ADR-0063 did.
- A native shell (React Native) starts -- confirm this tab-bar model maps onto the
  platform's own tab navigator rather than being re-derived.
