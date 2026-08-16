# ADR-0017: Archetype-based card rendering, color-only highlighting, motion

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav, Mayank

## Context

Feedback on the shell redesign (ADR-0012 through 0016): everything but the middle feed
reads well. The feed itself — a uniform stack of title+summary cards that open to a
plain scrolling text body — is not something a reader wants to keep scrolling through.
Every card looks and behaves identically regardless of what it actually contains, which
reads as monotonous rather than as a deliberate, textbook-honest pace.

## Decision

### Hybrid disclosure by archetype

Not every card collapses to the same shape. `card.archetype` (a set of tags —
`code`/`diagram`/`comparison`, any subset, `[]` for plain prose; see
content-model.md's "On archetype") drives which collapsed-preview shape a card gets:
a language badge + one-line teaser for code, a condensed breadcrumb for a diagram, two
inline ❌/✅ tags for a comparison, unchanged title+summary for plain prose. The expanded
view always renders the full body regardless of archetype — the tag only picks the
collapsed teaser.

**Archetype is derived, never LLM-self-reported.** content/archetype.py runs a
deterministic classifier against `body` after it exists — a fenced code block, diagram
characters, or a ❌/✅ pair are objectively present or not, unlike `difficulty` (a
judgment call, which is why the quality gate independently re-rates it rather than
trusting the request). Asking the model to also tag structure it already wrote would be
a second, occasionally-wrong source of truth for something a regex gets right for free.
The generation prompt is still expected to *use* these shapes where a subtopic calls for
it — a real command example in a fenced block rather than prose describing one — the
same spirit as `summary` being a purpose-written hook rather than a truncation.

**"Hero" is not an archetype tag.** No reliable signal exists for "this is a core
mental model" without an actual curation or judgment pipeline — a bigger piece of work
than this pass covers. v1 renders the first card in each feed station as hero-styled
(always expanded, larger type, left accent border) purely as a feed-layout decision, not
a property of the card itself. A follow-up task should cover a real curated `is_hero`
flag if this simplification doesn't hold up.

### Color-only keyword highlighting, two tiers

No new markdown syntax. `**bold**` keeps meaning "primary concept" (`--accent`, already
in place since ADR-0012); inline `` `code` `` becomes "technical syntax/parameter" — its
background pill is dropped (color-only, not a fill) and it's recolored to a new
`--accent-syntax` token, distinct in hue from `--accent` everywhere that's meaningfully
possible:

| Palette | `--accent-syntax` | Why |
|---|---|---|
| Notebook | `#2f6b78` (teal-blue) | New value; theme had no second hue |
| Copper Board | `#5fb4d9` (sky cyan) | New value; theme had no second hue |
| Skylight (cyanotype) | `#b5793f` (warm terracotta) | Opposite temperature from its own blue `--accent` — same hue would collapse the two tiers |
| Obsidian (phosphor) | `#a8a8ab` (mid-gray) | **No new hue** — ADR-0016 committed this theme to strict monochrome; the two-tier hierarchy comes from brightness (dim gray vs. near-white) instead of color |
| Oscilloscope (scope) | `#e8a33d` (reuses existing `--accent-2`) | Already had two genuinely distinct hues; no new value needed |

### Motion: Framer Motion added as a dependency

First dependency beyond next/react/react-dom. Justified by a problem the codebase's own
CSS comments already document failing to solve twice with pure CSS: `grid-template-rows:
0fr → 1fr` doesn't animate in Chrome, and measured-height + `requestAnimationFrame`
breaks under React's development double-invocation. Framer Motion's `layout` animation
is a FLIP implementation that solves exactly this, and its `drag` API gets swipe-to-
dismiss gestures essentially for free rather than hand-rolled pointer-event math.

Swipe-right on a card is an **alternate gesture for the existing "mark seen" action**
(`gotIt`), not a new business rule — no new engagement event type. It does introduce one
real behavior change: today a seen card stays visible in place; after a swipe
specifically (not after tapping the checkmark) the card is removed from the current
render's list, matching "swipe right... pulls up the next card." This is a client-side
rendering change only — the card's seen/state data is untouched, and it can still be
read again via Liked/Saved or a future session.

### Scroll-snap: scale/opacity focus effect, deliberately without hard `scroll-snap`

The reference spec calls for `scroll-snap-type: y mandatory` on the scrolling
container. The feed's actual scrolling element is the **window/body**, by explicit,
documented design (`globals.css`'s header comment: cards scroll at the window level
specifically to avoid a Chromium/WebKit repaint bug that occurs when a `position:
sticky` element sits inside a clipped/rounded ancestor). Forcing mandatory snap on
`body` would fight that same sticky `.station` header and fight in-place height changes
during expand/collapse.

Implemented instead: the same `IntersectionObserver` pattern already used for impression
tracking (`Card.tsx`) drives a scale/opacity "focus" effect — closer to center gets
`scale-100`/`opacity-100`, further gets `scale-95`/`opacity-50` — without forcing the
scroll position to stop anywhere. Gets the visual pull toward the centered card without
risking the documented sticky-header bug or fighting variable card heights across
expand/collapse.

## Consequences

**Easier**
- The feed reads as varied — format changes as often as content does, which is closer
  to what actually holds attention scrolling.
- Two-tier color hierarchy pulls the eye to the 2-3 words that matter before the
  sentence is read.
- Fluid expand/collapse and swipe gestures, without hand-rolling FLIP animation or
  pointer-event drag math.

**Harder**
- First non-trivial frontend dependency — bundle size and an upgrade surface that didn't
  exist before.
- `archetype` only reflects what's textually in `body`; a card can be miscategorized
  as prose-only simply because the model didn't reach for a fenced block even where one
  would help. Content quality (does the prompt actually produce code/diagrams where
  useful) is a separate, ongoing concern from the classifier being correct.
- Hero's "first card in station" heuristic is not curation — a topic whose first
  generated card isn't actually its most important idea gets an arbitrary hero.
- Swipe removing a card from view (vs. tap-to-mark, which doesn't) is an inconsistency a
  user has to learn — two gestures for the same action with different visual outcomes.

## Alternatives considered

**LLM self-reports `archetype` in the same structured-output call as `title`/`summary`.**
Rejected — see "Decision" above; this is the same self-report-validates-nothing problem
`difficulty` already solved by requiring independent verification, except here
independent verification is free (a regex), so there's no reason to introduce a
self-report at all.

**Five archetype-specific card components instead of one dispatching component.**
Rejected — the engagement/dwell/seen-state interaction logic in `Card.tsx` is shared and
non-trivial; duplicating it five ways risks subtle engagement-tracking divergence across
archetypes for no benefit, since only the preview/expanded rendering actually differs.

**Hard `scroll-snap-type: mandatory`, per the reference spec literally.** Rejected for
now — see "Decision." Revisit if the softer scale/opacity effect doesn't feel like
enough once it's actually in front of users; true hard snapping would likely require
giving each card its own scroll container, a real structural change bigger than this
pass.

## Revisit when

- The corpus actually has enough code/diagram/comparison cards generated (not just the
  hand-added fixture examples) to judge whether the classifier's detection holds up on
  real model output.
- Hero's "first in station" heuristic feels wrong often enough to justify a real curated
  `is_hero` flag.
- Users report the scale/opacity focus effect doesn't pull attention enough — that's the
  signal to revisit hard scroll-snap.
