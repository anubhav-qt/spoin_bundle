# ADR-0037: Implement ADR-0023's font picker, site-wide, with live-preview/revert

- **Status:** Accepted
- **Date:** 2026-08-18
- **Deciders:** Anubhav

## Context

[ADR-0023](0023-reader-font-selection.md) already decided the *what*: five selectable
faces (Literata default, Inter, Space Grotesk, IBM Plex Sans, Atkinson Hyperlegible),
`--font-mono` locked out of the choice (ADR-0021's ASCII column budget depends on it
staying fixed-width), applied via a `data-font` attribute + `localStorage`, the same
mechanism the palette picker already uses. It was written and accepted but never built —
`app/layout.tsx` still carries a comment stating "System stacks only — no next/font,
nothing to self-host," and no `FontPicker` component or `data-font` CSS exists anywhere
in the codebase. This ADR is the implementation decision, not a reopening of ADR-0023's
choices: same five faces, same locked mono, same attribute/localStorage shape.

Two things ADR-0023 left genuinely open, which this ADR resolves:

1. **How to self-host without hand-managing font files or bundle weight.** ADR-0023
   flagged "only the selected family should load" as a real risk of a naive
   implementation.
2. **The interaction pattern for trying a font before committing to it.** The punch-list
   item asks for live preview with an explicit Keep/Revert choice, which ADR-0023 didn't
   specify (it only covered persistence, not the in-session trial UX) — this is the one
   genuinely new decision in this ADR.

## Decision

**Self-hosting via `next/font/google`**, not manually downloaded/subset font files. Each
of the five faces is loaded through Next's built-in Google Fonts integration, which
downloads and self-hosts the font files at build time (no runtime CDN request, satisfying
ADR-0023's requirement) and exposes each as a CSS custom property
(`--font-literata`, `--font-inter`, etc.) via a `variable` class applied once on `<html>`.
Declaring all five this way does **not** mean all five download to every reader: a
browser only fetches an `@font-face` source when text on the page actually resolves to
that `font-family` and needs glyphs from it. Since `--font-sans` (the property that
actually renders text) only ever points at *one* of the five `--font-<name>` variables at
a time (set by `[data-font="..."]` on `body`, mirroring `[data-palette="..."]`), the other
four `@font-face` rules exist in the stylesheet but are never triggered — so ADR-0023's
"only the selected family should load" holds without any conditional-import machinery.

**Application scope matches ADR-0023's stated scope exactly: `--font-sans`, not a new,
narrower "reader-only" variable.** `body`'s base `font-family: var(--font-sans)`
(`globals.css`) is the only declaration that needs to become font-selectable, and because
everything but `--font-mono`-tagged chrome inherits from `body`, this reaches prose,
titles, and general chrome in one place — "site-wide" was never actually a scope
expansion beyond what ADR-0023 already specified, just the part that hadn't been wired
up. `--font-mono` stays hardcoded to the system stack, untouched, per ADR-0023.

**Live preview with Keep/Revert:** selecting a face in the picker applies it immediately
(`data-font` set on `body`, matching `ThemePicker`'s existing live-apply behavior) but
does **not** write to `localStorage` yet. A small inline confirmation ("Keep this font?"
Keep/Revert) appears in the picker until resolved. **Keep** persists the selection to
`localStorage["spoin-font"]`. **Revert** re-applies whatever `data-font` value
`localStorage` held before the preview started (or removes the attribute entirely if
nothing was persisted yet, falling through to the default `literata`). Picking a
*different* face while a preview is pending replaces the pending preview rather than
stacking confirmations — there is only ever one open preview at a time.

## Consequences

**Easier**
- Follows an established mechanism exactly (attribute + localStorage + pre-hydration
  script), so no new persistence pattern to learn or maintain.
- `next/font/google`'s automatic self-hosting means no manually vendored `.woff2` files,
  no license-file bookkeeping beyond what ADR-0023 already committed to (OFL faces only).

**Harder**
- Five `next/font/google` declarations at build time means `next build`/`next dev` needs
  network access to fetch the font files (once, cached by Next's build cache after that).
  A fully offline build environment cannot compile this until the fonts are vendored
  once with a live connection.
- The Keep/Revert confirmation is genuinely new UI state (a pending, unpersisted
  selection) that every other picker in this app (palette) doesn't have — worth watching
  for whether it reads as an inconsistency against `ThemePicker`'s plain "click and it's
  saved" behavior, since the two pickers now behave differently by design.
- ADR-0023's own "Harder" consequences (re-tuning line-height/measure per face, five
  self-hosted families' bundle weight) are inherited unresolved here — this ADR is the
  wiring, not a retune pass.

## Alternatives considered

**Apply the picker to a new `--font-reader` variable, scoped to card body text only,
leaving titles/chrome on the system stack.** Rejected — this is what "site-wide" in the
punch list was actually pushing back against, and it contradicts ADR-0023's own text
("governs `--font-sans` — prose, titles, chrome — only"), which already specified
site-wide-minus-mono. Re-scoping it narrower now would be quietly reversing an accepted
decision without saying so.

**Auto-persist on selection, no Keep/Revert.** Matches `ThemePicker`'s existing pattern
exactly and is simpler. Not chosen because the punch-list item explicitly asked for a
trial step — font legibility is harder to judge from a swatch than color is, so trying it
against real content before committing is the actual value being asked for here.

## Revisit when

- If build-environment network access to Google Fonts becomes unreliable, switch to
  `next/font/local` with the five `.woff2` files vendored into the repo once — same
  CSS-variable shape, no picker-side change needed.
- If the Keep/Revert pattern proves confusing next to `ThemePicker`'s plain apply-and-save
  behavior, consider bringing both pickers to the same interaction model rather than
  leaving them permanently divergent.

## Default font override (2026-08-27, developer's choice)

The shipped default is now **Space Grotesk** (`grotesk`), not Literata — a taste call by
the project owner, paired with the Obsidian palette default
([ADR-0012](0012-feed-visual-design.md)). Unlike Literata (which is the bare `:root`
`--font-sans`), `grotesk` has its own `[data-font="grotesk"]` block, so the attribute is
now **always set** — `applyFont` no longer clears it to mean "default", and
`app/layout.tsx`'s pre-hydration script writes `data-font="grotesk"` when nothing is
stored. The five faces and the Keep/Revert flow are unchanged. Revert by pointing
`DEFAULT_FONT` and the script back at `literata`.
