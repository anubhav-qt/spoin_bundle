# Task 0002: Palette selection UI -- onboarding picker + settings switcher

> **Update (ADR-0013, three-column shell):** the right-rail `ThemePicker` now ships -- five
> live pills, click-to-switch, `localStorage` persistence, applied pre-hydration via an
> inline script in `layout.tsx` to avoid a flash of the default palette. That covers the
> "settings" half of this task's original scope, since the persistent right rail is the
> closest thing the app has to a settings surface today. **Still open:** the onboarding
> flow (palette choice as part of first-run setup) -- nothing here changes that part.

- **Owner:** unassigned
- **Timebox:** ~1 day
- **Depends on:** [ADR-0012](../adr/0012-feed-visual-design.md) (the five palettes and the
  `data-palette` token system it defines). That ADR ships the tokens with one hardcoded
  default; this task is what lets a user actually choose.
- **Background reading:** [`docs/design/mockups/feed-palettes.html`](../design/mockups/feed-palettes.html)
  -- the five palettes, live, with the rationale for each.

## The problem

ADR-0012 committed to five full color palettes (Copper Board, Cyanotype, Phosphor,
Notebook, Oscilloscope) rather than one theme with a light/dark toggle. Right now the app
just hardcodes one of them (`copper`) on `<body data-palette>`. Nothing lets a user pick a
different one, and nothing persists the choice.

Two surfaces are missing, not one:

1. **Onboarding** -- new users choose a palette as part of first-run setup, alongside
   whatever else onboarding already asks (topics, entry difficulty). This is a first
   impression: it should feel like picking an identity for the app, not a settings
   checkbox buried on page one.
2. **Settings** -- existing users can change their mind later. There is currently no
   settings surface in the app at all, so this task may be the thing that creates one.

## What "done" looks like

- A picker component that renders all five palettes as live previews (not just color
  swatches -- a miniature card or two in each palette reads much better, per how
  `feed-palettes.html` presents them) and lets the user select one.
- The same component (or a thin wrapper around it) works in both onboarding and settings --
  do not build two different pickers.
- Selection persists (`localStorage` is enough for v1, matching the pattern the old
  light/dark toggle used before this ADR superseded it -- see the removed `cycleTheme` in
  `Feed.tsx`'s git history) and survives reload.
- Falls back sensibly for a user who never sees onboarding (e.g. an existing seeded
  account) -- pick one palette as the global default and say so in code, don't leave it
  implicit.

## Deliberately not required

- A live "system" auto-mode that picks a palette based on OS light/dark preference. That
  concept doesn't really apply here -- four of the five palettes are dark-native and one is
  light-native by identity, not as a paired light/dark option (see ADR-0012's "Consequences").
  If this feels like a real gap once the picker exists, raise it as a new ADR rather than
  smuggling it into this task.
- Syncing the choice server-side. Local-only is fine until there's a reason (multi-device)
  to do more.

## Related

The palette token set itself (`--bg`, `--fg`, `--accent`, etc. under `[data-palette="x"]`)
already exists in `apps/web/app/globals.css` -- this task is UI and persistence on top of
it, not new tokens.
