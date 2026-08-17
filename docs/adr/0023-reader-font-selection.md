# ADR-0023: Five selectable reader fonts, with the monospace face locked

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

[ADR-0012](0012-feed-visual-design.md) shipped five palettes and
[ADR-0016](0016-theme-consolidation.md) made them five _visually distinct_ choices. The
palette picker is the product's only real customization surface, and it works: choosing
your own reading environment is a meaningful act of ownership in an app you're meant to
open daily.

Typeface is the other half of that environment, and for a product that is almost entirely
text it arguably matters more than color. Reading preference is genuinely personal and
genuinely divided — serif versus sans is not a question with a correct answer, and
readers with dyslexia or low vision have needs a single house font cannot serve.

The whole mechanism already exists. Palettes are a `data-palette` attribute on the root,
persisted in `localStorage`, applied by a pre-hydration script so there is no flash of the
wrong theme. Fonts are the same shape of problem.

One new constraint makes this decision non-trivial: [ADR-0021](0021-ascii-scene-library.md)
introduces ASCII scenes authored to an exact 40-column budget. That budget is only real if
the characters are fixed-width.

## Decision

Ship five selectable reader fonts, on the palette mechanism: a `data-font` attribute on the
root, persisted in `localStorage`, applied by the same pre-hydration script, exposed by a
picker next to the theme picker.

### The locked monospace face

**`--font-mono` is not part of the choice.** ASCII scenes and code blocks render in one
fixed, known monospace face regardless of the reader's selection. The selection governs
`--font-sans`/`--font-serif` — prose, titles, chrome — only.

This is the load-bearing sentence in this ADR. Without it, the first reader who picks a
font whose fallback chain isn't fixed-width silently destroys every ASCII scene in the
corpus, and nothing anywhere reports an error.

### The shipping set

Five faces chosen to be distinguishable at a glance in the picker — the same bar
ADR-0016 applied to palettes, where two options that differ only in a side-by-side
swatch comparison are effectively one option.

| Key            | Face                  | Why it's in the set                                                                        |
| -------------- | --------------------- | ------------------------------------------------------------------------------------------ |
| `literata`     | Literata              | Reading serif, designed for long-form screen reading. **Default.**                         |
| `inter`        | Inter                 | Neutral neo-grotesque; the "no opinion" choice                                             |
| `grotesk`      | Space Grotesk         | Geometric with real personality; pairs with the terminal-leaning palettes                  |
| `plex`         | IBM Plex Sans         | Slightly technical humanist sans; distinct from Inter in the ways that matter at body size |
| `hyperlegible` | Atkinson Hyperlegible | Drawn specifically to disambiguate similar glyphs for low-vision readers                   |

All five are OFL/open-licensed and **self-hosted and subset** — no CDN, no third-party
request, no layout shift while a webfont arrives.

Literata is the default rather than Inter because the shipped default palette is Notebook
(ADR-0012) and the product's honest self-description is closer to a textbook than to a
dashboard. This is the one choice in this ADR that is cheap to reverse.

### The combinatorics are accepted, not managed

Five fonts times five palettes is twenty-five combinations, and some will be ugly. We are
not building per-palette font restrictions or a curated pairing matrix. The point of a
customization surface is that the reader's taste wins, including when it differs from
ours. What we _do_ commit to is that all five faces are legible at body size in all five
palettes — legibility is our floor, aesthetics is their call.

## Consequences

**Easier**

- Readers with a real preference or a real need get served, and the product's
  customization story becomes "make it yours" rather than "pick a color".
- Zero new mechanism: attribute, `localStorage`, pre-hydration script, picker — all four
  already exist and are already debugged.

**Harder**

- Five self-hosted, subset font families is real bundle weight. Only the selected family
  should load; a naive implementation that ships all five to every reader would be a
  significant regression on a product whose first impression is time-to-first-card.
- Every typographic value tuned against one face — line-height, measure, heading scale,
  the two-tier `--accent`/`--accent-syntax` weight hierarchy from ADR-0017 — now has to
  hold across five faces with different x-heights and metrics. Expect to re-tune, and
  expect at least one face to need a per-font line-height override.
- A second picker adds visual weight to the chrome, which the shell redesign has been
  actively fighting to keep quiet.
- Licensing is now a thing we own. Every face must stay OFL/open, and adding a sixth is
  not just a design decision.

## Alternatives considered

**Let the font choice include the monospace face too.** Rejected — see "Decision". It
breaks ADR-0021 silently and corpus-wide.

**Two options (a serif and a sans) instead of five.** Rejected: it covers the actual
readability axis but not the ownership one, and it wouldn't include Atkinson Hyperlegible,
which is the choice in the set that serves a need rather than a taste.

**A system-font stack only, no webfonts.** Genuinely the cheapest option and the fastest —
zero bundle weight. Rejected because it makes the product look meaningfully different on
every OS, which contradicts the whole premise of shipping a designed, committed visual
identity (ADR-0012's five palettes exist precisely so the reading environment is
deliberate rather than inherited).

**Curated font/palette pairings instead of a free 5×5 grid.** Rejected as
over-management: it substitutes our taste for the reader's on the one surface explicitly
built to hand them control, and it doubles the picker's conceptual complexity to prevent
an outcome ("that looks bad to me") that costs one click to undo.

## Revisit when

- Bundle/latency measurements show font loading materially delaying first card render —
  the signal to cut the set or change the loading strategy, not to abandon the feature.
- Selection telemetry shows two of the five faces essentially unused, which is the same
  near-duplicate signal ADR-0016 acted on for palettes.
- ADR-0021's scene library is ever retired or moves off character-grid rendering, at which
  point the monospace lock has no justification and should be dropped rather than
  inherited.
