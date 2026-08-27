# ADR-0012: Feed visual design -- Thread layout, five committed palettes

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

The web app had a first-pass visual design ("Beads": a thread line with beads down the
left, lilac/periwinkle palette, Nunito throughout) but no product decision behind it -- it
was never compared against alternatives. Before building out the rest of the frontend, we
mocked up three fundamentally different interaction shapes for the feed and, once one was
picked, five different color treatments of it, using real corpus content (Kubernetes,
Distributed Systems) rather than lorem ipsum. Both rounds are preserved as standalone HTML
in [`docs/design/mockups/`](../design/mockups/) -- `feed-directions.html` and
`feed-palettes.html` -- and are the source of truth for the visual language: build from
them, don't redraw from memory.

## Decision

### Interaction shape: Thread

Three shapes were mocked up:

- **Thread** -- a scroll of collapsed cards grouped under sticky station labels (topic, or
  subtopic when filtered to one topic -- [`stations.ts`](../../apps/web/lib/stations.ts)
  already implements this grouping rule and is unaffected by this ADR). Tap a card to
  expand it in place.
- **Swipe** -- one card fills the viewport; dots track progress; arrows or a swipe gesture
  move between cards.
- **Hybrid** -- a lightweight thread for browsing, tapping opens a focused bottom sheet for
  the actual reading and completion moment.

**Thread won.** It matches how a knowledge feed actually gets used -- comparing cards,
skimming several topics in one session -- better than forcing one card at a time. Swipe was
kept as a mockup rather than discarded: it maps cleanly onto quiz UI later (one question at
a time, progress dots, forward/back), which the feed itself doesn't need but the quiz
almost certainly will.

### Card interaction: toggle-expand, icon-only actions, Got it moves to the action row

Three changes to how a card behaves, made while wiring the Thread design into
`apps/web`, past what the mockups originally showed:

- **Cards expand and collapse independently.** Opening a second card no longer closes the
  first -- both can be open at once. Only a click that lands outside every card (empty gaps,
  masthead, margins) collapses whatever is open. Clicking a card's own body while it is
  expanded now also closes it (a true toggle), not just click-outside and Escape.
- **All five actions (like, save, note, ask AI, share) are icon-only**, each its own small
  circular outline button -- no visible text label. `aria-label` carries what the text used to.
- **"Got it" moved from a text pill at the end of the expanded body to a circular icon at the
  extreme right of the action row**, separated from the other five by a flex spacer so it
  reads as a different _kind_ of action, not a sixth item in the row. It is **toggleable** --
  tapping it again turns the local indicator back off, since a stray tap on a 28px circle is
  easy to make. The text pill in the expanded body is gone entirely; this icon is the only
  "Got it" affordance now.

**This directly reopened a decision content-model.md made deliberately** (see the "Got it"
paragraph under "Engagement surface" there, now marked superseded): moving the icon into the
action row made it reachable on a **collapsed** card, so tapping it could fire
`explicit_complete` and satisfy `SEEN` **without expansion ever happening** -- silently
breaking ADR-0010's "Scrolling past never counts. Expansion is required" rule.

**Resolved:** the icon is now `disabled` until the card has been expanded at least once this
session (`Card.tsx`'s `everExpanded` state -- sticky across a later collapse, so the icon stays
usable once earned rather than re-locking every time the card closes). This keeps the fast
"I already know this" toggle while still requiring one look at the content first, restoring
ADR-0010's rule rather than quietly dropping it. The two options not taken:

- Ship it reachable pre-expansion and accept the gap, on the theory that ADR-0010 already
  tolerates a weak completion signal for `dwell_complete`. Rejected -- that precedent is about
  signal _strength_, not about skipping the expansion requirement entirely; the two are not
  the same risk.
- Keep it pre-expansion-reachable but weight it as a third, weaker tier of completion signal
  in ranking. Rejected for now: it's a backend change (`EngagementKind`,
  `apps/api/src/spoin/domain/enums.py`) with no clear benefit over just requiring expansion,
  which is free.

### Typography: system stacks, mono for chrome

`ui-sans-serif` for reading content, `ui-monospace` for everything that is system
chrome rather than prose -- topic labels, difficulty pips' `aria-label`, station headers,
the eyebrow/status text. This replaces the single Nunito face used everywhere in "Beads".
The split carries meaning: monospace reads as _the system talking to you_ (labels, state,
metadata), proportional sans as _the content itself_. No webfonts -- system stacks only,
so there is nothing to self-host or risk a silent fallback on.

### Color: five committed palettes, not one theme with light/dark

Five full palettes were designed, each a specific engineering artifact rather than an
arbitrary hue choice:

| Key         | Name         | Reference                                                                  | Natural mode |
| ----------- | ------------ | -------------------------------------------------------------------------- | ------------ |
| `copper`    | Copper Board | populated PCB, copper trace on dark laminate                               | dark         |
| `cyanotype` | Cyanotype    | ~~the actual chemical-print blueprint blue~~ -- see below                   | light        |
| `phosphor`  | Phosphor     | ~~CRT terminal glow, desaturated so body text stays readable~~ -- see below | dark         |
| `notebook`  | Notebook     | squared engineering paper, graphite ink, red-pencil accent                 | light        |
| `scope`     | Oscilloscope | dual-trace readout, cyan primary + amber secondary channel                 | dark         |

> **Superseded in part by [ADR-0016](0016-theme-consolidation.md):** Copper Board and
> Phosphor converged visually (both near-black with one warm/green accent), and Notebook
> was the only light palette. `phosphor` and `cyanotype` were redefined -- Phosphor to a
> strictly monochrome black/gray dark theme, Cyanotype to a soft, light blue-toned theme --
> rather than kept as the chemical-print/CRT identities described in this table. The keys
> and the "five full palettes, not light/dark toggle" decision below still stand; only
> those two identities changed.

**All five ship.** This is a departure from the usual "pick one, design light and dark
variants of it" approach: each palette here is a full, deliberate world (per
`artifact-design` guidance, a design that commits to one visual identity is allowed to
skip the light/dark pairing and commit outright), and the user chooses _which world_,
not light-vs-dark within a single world. `notebook` happens to be light-native and the
other four dark-native, but that is incidental to their identity, not a paired axis.

The token set (`--bg`, `--bg-2`, `--bg-3`, `--fg`, `--fg-2`, `--fg-3`, `--accent`,
`--accent-2`, `--line`, `--line-strong`, `--good`, `--shadow`) is identical across all
five, switched by a `data-palette` attribute. Component CSS reads only the tokens, never a
literal color, so adding a sixth palette later is additive.

### Selection: deferred to onboarding + settings, not decided today

The mechanism for a user to _pick_ a palette (onboarding) and _change_ it later
(settings) is **out of scope for this ADR** -- no onboarding flow and no settings screen
exist yet. See [task 0002](../tasks/0002-palette-selection-ui.md). This ADR only commits
to: the five palettes exist as a token system, one is used as the shipped default until
the picker exists, and nothing in the component layer assumes there is only one palette.

## Consequences

**Easier**

- Adding a sixth palette is a new `[data-palette="x"] { ... }` block; no component touches
  a literal color.
- The mockups are real, working HTML -- copy-paste starting points for the actual
  components rather than a picture to redraw from.

**Harder**

- No light/dark toggle in the old sense. A user who wants "dark but not phosphor-green"
  has to pick among the dark-native palettes rather than getting light/dark as an
  independent axis from color identity. Accepted: light/dark was never really independent
  of identity for four of these -- a copper-board world in "light mode" isn't a coherent
  thing.
- Five palettes to keep visually correct (contrast, accent legibility) as the component
  set grows, instead of one.

**Committed to**

- Component CSS reads tokens only, never a literal hex value.
- `docs/design/mockups/*.html` stays in sync with what ships -- if the real components
  diverge, the mockups get updated too, not left to rot as a historical artifact.

## Alternatives considered

**One palette, light + dark variants (the usual approach).** Rejected: none of the five
identities survive being inverted into a "light mode" version of itself without becoming
generic. Cyanotype-but-light is not blueprint paper, it's just pale blue.

**Keep "Beads" (lilac/periwinkle, Nunito).** Rejected after direct comparison -- no
articulated reason it looked the way it did, and thin against a subject that is
fundamentally about systems and engineering knowledge.

**Ship only the winning palette now, defer the other four.** Rejected: the token
indirection costs nothing extra to build for five instead of one, and building it for one
now means redoing the theming pass later instead of just adding rows to a table.

## Revisit when

- The onboarding/settings picker (task 0002) ships -- this ADR's "one default until then"
  clause is satisfied and can be removed.
- Real usage shows a palette nobody picks -- worth asking why before quietly dropping it.
- The quiz UI gets designed -- the Swipe mockup is the deliberate starting point for that,
  not a rejected direction.
- Real usage shows the expansion gate on the Got it icon is more friction than signal --
  e.g. if the 80% coverage gate turns out to need the fast per-card toggle unblocked before
  first open, revisit the two rejected options in "Card interaction" above.

**Extended by [ADR-0013](0013-topic-relationship-graph.md)/[ADR-0014](0014-progress-insights-panel.md):**
the desktop shell moved from single-column to a three-column layout (left nav, center
thread, right rail with the theme switcher, topic filter, and a progress-stats panel -- see
ADR-0014 for why that last slot isn't the relationship graph ADR-0013 originally shipped).
The palette/typography/card decisions here are unchanged; only the outer shell around the
thread changed.

**Developer's pick marker (2026-08-27):** the theme picker shows a small accent dot on
**Obsidian** (`phosphor`) and the font picker on **Space Grotesk** (`grotesk`) -- a
`data-devchoice` attribute + `::before` corner dot, tooltip "… · developer's pick". It is
cosmetic only: the shipped default is still Notebook / Literata (`DEFAULT_PALETTE` /
`DEFAULT_FONT` unchanged), nothing is pre-selected, and this is not a re-run of the
palette comparison above -- just a signposted recommendation. Font side:
[ADR-0037](0037-site-wide-font-picker.md).
