# ADR-0046: One collection surface shared by Saved, Liked, Profile and Settings

- **Status:** Accepted
- **Date:** 2026-08-21
- **Deciders:** mayanks0ni
- **Relates to:** [ADR-0012](0012-feed-visual-design.md) — the token system and the
  five-palette rule are unchanged. This is about the four non-feed pages, which ADR-0012
  never covered.

## Context

ADR-0012 established the design tokens and the Thread layout for the feed. The pages
built since — Liked, Saved, Profile, and now Settings — were each built separately, and
each grew its own copy of the same furniture.

Measured rather than asserted: **27 of the 31 `.liked-*` CSS rules had a byte-equivalent
`.saved-*` twin.** Eyebrow, subtitle, metadata line, divider, search field, sort pills,
filter chips, CTA, error block, footer — two copies, ~400 lines. `get_saved_cards`'s own
docstring said "Mirrors `get_liked_cards` exactly," and a diff put the two handlers at
74% identical.

Three symptoms followed from that, all of which had already happened:

1. **Drift.** The Liked page's metadata line counted its own cards as `"SAVED CARDS"` —
   a copy-paste that survived because there was nothing to compare against.
2. **Three different page widths.** Liked and Saved were `max-width: 640px` with px
   padding; Profile was `48rem` with rem padding. On mobile it was worse: `.app-grid`
   inherited `align-items: start` into its single-column fallback, which on a column
   flexbox means shrink-to-fit, so each page sized itself to its own widest child —
   Saved measured 324px and Profile 209px **at the same viewport**.
3. **Unstyled surfaces.** `EditProfileModal` referenced `topic-modal-*` and `card-input`,
   class names with zero definitions anywhere in `globals.css`. It rendered as raw
   browser chrome and had done since it was written.

A user moving between these pages was moving between three templates.

## Decision

**The four collection pages share one CSS layer, `.collection-*`, and the shell owns the
gutter.**

```
.collection-view      one measure, one vertical rhythm
.collection-header    eyebrow + title + metadata
.collection-rule      the divider
.collection-controls  search, .collection-pill (sort), .collection-chip (topic filter)
.collection-action    the button, in three weights
.collection-state     empty / error / loading, one vocabulary
.collection-footer    the watermark
```

Page-specific vocabulary stays page-specific: Liked's vertical card list, Saved's tile
grid and overlay, Profile's figures and graphs, Settings' rows.

**The shell owns horizontal padding.** `.shell` already had `padding: 0 18px` and each
view added its own 14–16px on top, so these pages rendered ~32px narrower than a feed
card at every width. The views now set vertical padding only. A Saved tile lines up with
a feed card exactly.

**`align-items: stretch` in the `≤680px` fallback**, so every page is the same width on
mobile. This is a one-line fix to a shared rule, made deliberately rather than worked
around per-page, because the alternative is four pages each compensating for the same
inherited value.

**Modals use the house pattern.** `.modal-overlay` / `.modal-panel`, portal, Escape,
body-scroll-lock, `role="dialog"` — which every other modal in the app already used and
`EditProfileModal` alone did not.

## Consequences

**Easier**

- A change to how a collection page presents itself is one rule, not two-to-four.
- A new collection surface — Settings was the first test of this — starts with a masthead,
  a control bar and a full set of states, and inherits every accessibility affordance
  already in them.
- The drift class of bug is structurally gone: there is no second copy to disagree with.

**Harder**

- The layer is now load-bearing for four pages. A careless change to `.collection-pill`
  touches Saved, Liked, Profile and Settings at once — the cost of the thing that makes
  them consistent.
- `globals.css` grows a section that is not obviously owned by any one component, in a
  codebase with no CSS modules. The naming is the only boundary.
- Page-specific and shared classes now sit side by side in the same `className`
  (`"collection-view saved-view"`), which reads as redundant until you know why.

**Committed to**

- A new page in this family uses `.collection-*` for its masthead, controls, rules and
  states. Adding a fifth private copy is the thing this ADR exists to prevent.
- `.shell` owns horizontal padding. Views set vertical padding only.
- No page hardcodes a colour, duration or radius; ADR-0012's tokens remain the only
  source. Verified: zero literal hex values, `rgba()` calls or transition durations in
  the layer.

## Alternatives considered

**CSS modules or a component library.** The structurally correct answer to "shared styles
in one global file," and rejected as out of proportion. The problem was four copies of a
masthead, not the absence of scoping — and introducing a styling system mid-product would
touch every component, not the four that had the duplication.

**Extract shared React components** (`<CollectionHeader>`, `<CollectionControls>`) rather
than shared CSS. Rejected for now: the three pages genuinely differ in *what* they put in
the masthead and controls, and only agree on how it looks. Sharing the CSS captures the
agreement; sharing the components would have forced the disagreement into props. This is
the more likely next step if the pages converge further.

**Leave Profile out and unify only Liked and Saved.** The smaller change, and the one the
duplication measurement most obviously supports. Rejected because Profile was the page
most visibly a different template, and the mobile-width bug was invisible until all
pages were compared at once.

## Revisit when

- The masthead/controls props stop differing per page — that is the signal to promote the
  CSS layer into shared components. **Update 2026-08-30 ([ADR-0072](0072-revisit-drops-its-bespoke-grid.md)):**
  "Saved" (now "Revisit") dropped its bespoke tile grid + overlay and renders the same
  vertical `Card` list as Liked and Notes, so the three now differ only in copy and
  engagement kind. The component extraction this bullet anticipates is
  [task 0034](../tasks/0034-collectionview-rework-saved-notes-liked.md).
- A fifth page needs a collection surface *and* wants to differ structurally. Two pages
  wanting out is a sign the layer has over-generalised.
- CSS modules or Tailwind arrive for another reason. Then this layer is the first thing
  to port, and its class list is the spec for what to port.
