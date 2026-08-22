# ADR-0034: Per-topic accent color, composed with the active palette

- **Status:** Accepted (amended by [ADR-0051](0051-topic-color-opt-out.md))
- **Date:** 2026-08-18
- **Deciders:** Anubhav

> **Amended 2026-08-22 by [ADR-0051](0051-topic-color-opt-out.md).** `accent_hue`
> gains a third state, `-1` (`NO_TOPIC_COLOR`), meaning "opt out of topic color
> entirely, render the plain palette accent" -- alongside `null` (default hue) and
> `0-359` (a chosen hue) below. Same column, no migration.

## Context

The feed today has exactly one accent color at a time: `--accent`, set globally by
whichever of the five `data-palette` themes (ADR-0012, amended by ADR-0016) is active.
Every topic's cards render identically apart from text content — in a mixed feed
(multiple topics selected), there is no visual cue for which card belongs to which
topic short of reading the subtopic label.

The request is a per-topic accent that becomes that topic's card border/accent color,
with a sensible default and a user override. The hard constraint: this must **compose**
with the palette system, not fight it. A topic color that is a fixed hex independent of
the palette would look wrong in at least one of the five themes (e.g. a saturated
magenta sitting on Notebook's cream ground vs. Phosphor's near-black one) and would
defeat the palette picker's whole premise — every palette already defines its own
`--accent`/`--line`/`--bg-2` so any accent renders coherently against that palette's
ground.

Also relevant: cards are shared across users (overview.md) — the same `Card` row is
served to everyone subscribed to a topic. `Topic` is the canonical, shared entity;
`UserTopic` is "what THIS user calls it" (ADR-0004's shared-entity/personal-label
split, doc'd in `domain/models/topic.py`). A topic color is closer to "how I've labeled
this in my feed" than a property of the content itself — two users should be free to
color the same topic differently without it being a shared, contentious setting.

## Decision

**Storage: `UserTopic.accent_hue` (nullable smallint, 0-359), not `Topic.color`.**
Stored per-subscription, not on the canonical `Topic` row, following the same
shared-entity/personal-label split as `display_name`. A hue angle rather than a hex
value: storing a bare hue lets the color compose with whatever palette is active,
rather than needing separate light/dark hex values per palette. `null` means "use the
default."

**Default: deterministic, not random — and curated for the first 10 topics.** When
`accent_hue` is null, the client computes the default itself (`lib/topicColor.ts`), so no
write is needed just to have one. The first 10 topics a user follows (by subscription
order, i.e. index into the topics list — not the order cards happen to render in a mixed
feed) get one of 10 hand-picked hues spread evenly around the wheel (36° apart), so they
read as maximally distinct from each other rather than whatever a hash happens to
produce. Beyond the 10th followed topic, the default falls back to `hash(topic_id) %
360` — still deterministic, just no longer guaranteed distinct from its neighbors. No
migration needed to backfill existing `UserTopic` rows; they simply read as "using the
default" until a user picks one.

Note what curation buys and doesn't: because `--topic-accent` derives from
`oklch(from var(--accent) l c <hue>)`, every hue choice already inherits the active
palette's own lightness/chroma — the same values `--accent` was tuned with to read
clearly against that palette's background. Contrast against the page background is
therefore structurally guaranteed by the composition itself, not by which hue is picked.
What hue choice controls is contrast **between topics** — two similar hashes landing
near each other on the wheel would make two different topics look like the same color,
which is the actual failure curation avoids.

**Composition: a CSS custom property per card, mixed with the palette's own tokens —
never a bare hex.** `Card.tsx` sets `style={{ "--topic-hue": hue }}` on the card root.
New palette-relative tokens, defined once per palette alongside `--accent`:

```css
--topic-accent: oklch(from var(--accent) l c var(--topic-hue, h));
```

This takes the active palette's own accent color and rotates only its hue to the
topic's hue, keeping that palette's lightness/chroma — so a topic-colored card in
Notebook (light, high-contrast) and the same topic in Phosphor (monochrome dark) both
read as "this palette, tinted," never as a hex value dropped on top of five different
grounds. `.card[data-expanded="true"]`'s border-color and the hero ring's
conic-gradient stops (`globals.css:416`, `444-446`) switch from `var(--accent)` to
`var(--topic-accent)`. The collapsed (non-expanded, non-hero) card border stays
`var(--line)` as today — the accent shows on expand/hero, matching where `--accent`
already shows today, rather than tinting every idle card border.

Phosphor is explicitly monochrome by design (ADR-0016: "no color anywhere in the
palette"). `--topic-accent` is **not** overridden for Phosphor — topic coloring is
opt-out there, consistent with that palette's stated identity, rather than special-cased
per-card.

**User override:** `PATCH /topics/{id}/color` on `UserTopic`, body `{hue: int | null}`.
A small hue-swatch picker (12-16 preset stops, not a full color wheel — consistent with
`ThemePicker`'s discrete-choice pattern rather than a continuous input) lives in
`TopicStatsModal`, since that's already the per-topic detail surface item 1 of this
punch list extends.

## Consequences

**Easier**
- A mixed feed becomes visually scannable by topic without reading text.
- No new hex-per-palette data to maintain — one hue number covers all five palettes and
  any future one, since composition happens via `oklch(from ...)` at render time.
- Two users see the same topic in different colors without a shared-state conflict,
  matching how `display_name` already works.

**Harder**
- `oklch(from ...)` relative color syntax requires a reasonably modern browser
  (Chrome/Edge 119+, Safari 16.4+, Firefox 128+). No fallback is defined; on an
  unsupported browser the card silently keeps the palette's plain `--accent` (the
  `oklch(from var(--accent) ...)` declaration is simply invalid and ignored, leaving the
  prior `border-color: var(--accent)` … actually there is no prior declaration to fall
  back to once `--topic-accent` replaces it directly in the rule, so an explicit
  `var(--accent)` fallback value must ship alongside the `oklch()` one via two
  declarations in source order, the older browser using the first and ignoring the
  invalid second.
- One more per-card inline style (`--topic-hue`) and one more DB column having to be
  threaded through `TopicOut`/`UserTopic` reads.

## Alternatives considered

**Bare hex stored on `Topic`, shared across users.** Rejected: fights the palette system
directly (wrong on at least one of five grounds) and contradicts the shared-entity/
personal-label split every other per-user customization in this codebase follows.

**Full color picker (arbitrary hex) instead of a hue-only, palette-relative one.**
Rejected: an arbitrary hex reintroduces the exact "looks wrong against some palette"
problem this ADR exists to avoid. Constraining to hue-only and deriving lightness/chroma
from the active palette is what makes the two composable.

**A left-edge color stripe instead of a border-color/ring change.** Considered as a
lower-risk visual treatment (doesn't touch the existing expanded-border/hero-ring rules
at all). Not chosen only because it reads as a second, new visual affordance rather than
reusing the accent language the UI already has for "this card matters" — no strong
reason against it if `--topic-accent` composition turns out visually noisy in practice.

## Revisit when

- If `oklch(from ...)` browser support becomes a real constraint (analytics show a
  meaningful non-supporting audience), fall back to a precomputed per-palette hex lookup
  table instead of relative color syntax.
- If a topic ever needs a color visible to *all* subscribers (e.g. an editorially curated
  brand color for a flagship topic), that's a different, `Topic`-level field layered on
  top of this one, with `UserTopic.accent_hue` still taking precedence when set.
