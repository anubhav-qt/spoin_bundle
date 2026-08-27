# Task 0028: The right rail's own restructure from the responsive redesign

**Owner:** unassigned
**Status:** Mostly shipped on branch `responsive-mobile-shell` (items 1, 2, and most of
the chip / edge-alignment work). Items 3 (deep density pass) and 4 (Popular / For You
toggle) remain — see "Still open" below.

## Shipped (branch `responsive-mobile-shell`)

- **Utility row** is the four-up `DailyGoalRing` · Theme · Font · `FocusToggle` (item 1),
  Theme and Font as `PickerDropdown` controls (a labelled trigger + portalled popover
  reusing the existing swatch grid / `Aa` row), the ring fed from `AppShell`'s `dailyGoal`
  (item 2 — [ADR-0062](../adr/0062-daily-goal-ring-and-local-day-semantics.md)). The
  mobile Browse sheet keeps Theme + Font expanded, as required.
- Every utility column carries a `.picker-dropdown-label` so the four share a baseline:
  **"Today"** over the ring, "Theme" / "Font" from the dropdowns, a blank spacer over
  Focus. `FocusToggle` in the row is **icon-only** (no "Focus" text), per the canvas.
- Topic **filter** chips (`TopicRail`) rebuilt to the canvas shape — name / `62% · INT` /
  3px meter, `progress` threaded from `RightRail`. Re-adopts coverage + difficulty on the
  filter chip; see [ADR-0015](../adr/0015-topic-progress-and-discovery.md)'s amendment
  note. The old circular scroll-arrow buttons are replaced by a **minimal chevron pair**
  (borderless, `--bg`-halo glyph), rendered by `TopicRail` only on the side that can
  scroll — a plain mouse has no horizontal wheel axis, so the strip still needs a click
  target.
- **"View all topics"** is a plain uppercase mono text link under the chips (accent, no
  border / pill) — was a bordered `--bg-2` button.
- **`.progress-box` / `.discover-box` side padding removed** (`16px 0 2px`) so "Your
  topics" and "Discover" sit at the same left edge as the utility row; the row hover
  highlight is exactly content-width now (the `-14px` negative-margin bleed is gone —
  `.rail-right { overflow-x: hidden }` clipped it anyway).
- Not this task, but landed on the same branch: the `MobileNav` cut-over moved from
  `<=900px` up to `<=1100px` — the 3-column shell is too cramped below ~1120px. See
  [ADR-0064](../adr/0064-mobile-shell-tab-bar.md)'s ladder amendment.

## Still open

- **Item 3 — the deep `TopicsProgressBox` / `DiscoverBox` density pass.** The boxes are
  border-free with hairline row dividers already; what remains is the finer polish from
  the canvas: hair-thin meters tuned to match, the `.progress-row` caption line
  (difficulty tier + inline "Take quiz →" in accent), quiet mono captions on Discover
  rows. Verify at 1440 / 1280 / 1120 **and** in the mobile Browse sheet (same components).
- **Item 4 — the "Popular / For You" segmented toggle** on Discover (two square, not pill,
  buttons). Still gated on [task 0003](0003-personalized-topic-recommendations.md):
  `GET /topics/discover` has no "for you" mode. Build it with 0003, or ship the control
  wired to a client-side no-op with a comment pointing at 0003 — do **not** ship it
  looking live if it isn't. Decide with the product owner.

## Original brief

[ADR-0064](../adr/0064-mobile-shell-tab-bar.md) landed the mobile shell (tab bar, top
bar, Browse sheet, breakpoint ladder, left-nav hug). The same "Spoin Responsive and Mobile
App" design canvas also restyles the **desktop / laptop / tablet right rail itself**, and
that part was deliberately left out of ADR-0064 because it changes shared components used
at three widths and one piece needs an API that doesn't exist yet.

What the canvas asked for:

1. **Utility row 1** becomes, left to right: `DailyGoalRing` · **Theme** · **Font** ·
   `FocusToggle`. Theme and Font as **equal-width dropdown controls**. Mobile Browse sheet
   keeps the swatch grid + font list expanded. *(Done.)*
2. **`DailyGoalRing` in the rail**, fed by `AppShell`'s `dailyGoal`. *(Done.)*
3. **"Your topics" and "Discover" restyle** — border-free, hairline dividers between rows,
   hair-thin meters, quiet mono captions, inline "Take quiz →". Density / polish, not a
   redesign. *(Partly done — see "Still open".)*
4. **A "Popular / For You" toggle** on the Discover section — two square (not pill)
   segmented buttons. *(Open — gated on task 0003.)*

## Why it matters

The rail is what a desktop/tablet reader actually looks at every session. The mock's
version is tighter and reads as one system with the rest of the app; today's rail is three
stacked bordered boxes. Doing it as its own change (not folded into ADR-0064) keeps the
mobile shell reviewable on its own and keeps this diff scoped to the shared rail
components.

## What's left to do

- **Restyle pass on `TopicsProgressBox` / `.progress-*` and `DiscoverBox` / `.discover-*`**
  to finish item 3 (see "Still open" above). Check at 1440 / 1280 / 1120 (rail still
  shown) **and** in the mobile Browse sheet, which renders the same components.
- **Build the "Popular / For You" toggle** with [task 0003](0003-personalized-topic-recommendations.md),
  or ship the segmented control wired to a client-side no-op with a comment pointing at
  0003 — do **not** ship it looking live if it isn't. Decide with the product owner.

## What to hand back

- `npm run typecheck` + `npm run build` green (CI's `web` job).
- Screenshots at 1440 / 1280 / 1120 and of the mobile Browse sheet, showing the restyled
  "Your topics" / "Discover".
- A note on what was decided for the Popular / For You toggle.

## Timebox

Small now — items 1 and 2 shipped; what's left is one density/polish pass over two
components (rail + sheet render contexts to verify) plus the Popular / For You toggle,
which is a product decision gated on task 0003.
