# ADR-0016: Replace Phosphor with a monochrome dark palette, Cyanotype with a light one

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

ADR-0012 shipped five palettes, four of them dark-native (Copper Board, Cyanotype,
Phosphor, Oscilloscope) and one light-native (Notebook). In practice, Copper Board and
Phosphor read as near-duplicates in the theme picker: both are a near-black ground with a
single warm/green mid-brightness accent and comparable contrast — the kind of difference
that shows up in a side-by-side swatch comparison but not in a glance at the running app.

Separately, Notebook was the only light option among five palettes. A user who wants a
light UI has exactly one choice, and no path to a second one without also wanting graph
paper and a red-pencil accent specifically.

## Decision

Keep Copper Board as the reference dark-with-a-warm-accent palette. Retire the old
Phosphor and Cyanotype identities (CRT green glow; deep Prussian blueprint blue) and
redefine those two `data-palette` keys as:

- **Phosphor** — now a strictly monochrome black/gray dark theme: near-black ground,
  grayscale text ramp, and a near-white accent instead of a hue. No color anywhere in the
  palette. This is the "dark, no personality color at all" option Copper Board and Scope
  don't cover.
- **Cyanotype** — now a light theme with soft, muted blue tones (pale blueprint-blue
  ground, desaturated ink-blue text, a muted blue accent). This gives the picker a second
  light option alongside Notebook, so "I want light" isn't a single fixed identity.

The `key`s (`phosphor`, `cyanotype`) are kept rather than renamed, since they're what
`localStorage` persistence and `[data-palette]` selectors already reference — only the
token values and the swatch-preview colors in `globals.css` changed, plus the picker's
display order in `ThemePicker.tsx`. The display **names** shown in the hover tooltip
*did* change, since "Phosphor" (CRT green glow) and "Cyanotype" (blueprint-print blue) no
longer describe what's on screen: `phosphor` now shows as "Obsidian", `cyanotype` as
"Skylight". Same pattern already existed for `scope`, whose key doesn't match its display
name "Oscilloscope" either. The picker order was also changed to put `notebook`
first, since it's the shipped default (ADR-0012) and the leftmost position is the natural
place for it.

The grid-paper `--texture` (repeating-linear-gradient grid, previously Notebook-only) is
now defined for all five palettes, each using that palette's own `--fg` at a low alpha —
Phosphor previously had a different scanline-style texture; that's dropped in favor of the
same grid used everywhere else, for visual consistency across the picker rather than one
palette having a structurally different background pattern.

## Consequences

**Easier**
- The five palettes read as five visually distinct choices at a glance, not four
  dark-with-different-accents plus one light.
- A user who wants a light UI now has two real options with different personalities
  (graph-paper/red-pencil vs. soft blueprint-blue), not one.
- Consistent grid texture across all palettes instead of Notebook being the only one with
  a background pattern.

**Harder**
- This directly contradicts ADR-0012's own "alternatives considered" reasoning
  ("Cyanotype-but-light is not blueprint paper, it's just pale blue" was listed as a reason
  to reject a light Cyanotype). That reasoning held when Cyanotype's identity *was* the
  cyanotype print process. Here the identity itself is deliberately replaced, not
  reinterpreted in light mode — the old Cyanotype identity is gone, not lightened.
- `docs/design/mockups/feed-palettes.html` (ADR-0012's source-of-truth mockup) needs its
  Cyanotype/Phosphor blocks — CSS custom properties, swatch dot colors, and the
  descriptive copy — updated to match, so the committed mockup doesn't keep describing
  palettes that no longer exist in the app.

## Alternatives considered

**Rename the keys instead of keeping `phosphor`/`cyanotype`.** Rejected: no persisted
state or component logic needed to change beyond token values and picker order: keeping
the keys stable means a user's already-saved `localStorage` choice keeps resolving to
*a* palette (now redefined) instead of silently falling back to the default.

**Retire Phosphor and Cyanotype outright and design two palettes with new names.**
Rejected as unnecessary churn — five slots wired through picker, persistence, and
pre-hydration script already exist and work; only the identities inside two of them needed
to change.

**Make Copper Board the one retired instead of Phosphor.** Not chosen — no reason given to
prefer this over keeping Copper Board; Phosphor and Cyanotype were the two flagged as
needing to change.

## Revisit when

If a sixth palette slot is ever added, re-check whether the resulting set (2 light, 4
dark) still feels balanced, or whether light needs a third option.
