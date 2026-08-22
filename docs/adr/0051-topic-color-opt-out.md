# ADR-0051: A "no color" opt-out for per-topic accent, via a sentinel hue

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** Anubhav
- **Amends:** [ADR-0034](0034-per-topic-accent-color.md) -- `UserTopic.accent_hue`
  gains a third meaning for the same column; no new field.

## Context

ADR-0034 gave `UserTopic.accent_hue` two states: `null` ("use the deterministic
default hue") and `0-359` ("use this hue"). Every topic renders tinted, one way or
another -- there was no way to say "don't tint this topic at all, just use the
palette's own accent," which is exactly what `--topic-accent` already falls back to
whenever a card sets no `--topic-hue` (`globals.css`'s `--topic-accent: var(--accent)`
base case). That fallback already existed structurally; nothing exposed it as a user
choice.

The request is a "no color" option in the existing swatch picker (`TopicStatsModal`)
that lands on this fallback deliberately, for users who find per-topic tinting noisy
in a mixed feed or simply prefer every card to read as "this palette," unmodified.

## Decision

**A third state on the same `accent_hue` column, via the sentinel `-1` --
`NO_TOPIC_COLOR` in `lib/topicColor.ts`.** No migration: the column is already a plain
nullable `Integer` with no `CHECK` constraint, so a third meaning costs nothing on the
schema. `TopicColorIn.hue`'s validator widens from `ge=0` to `ge=-1`.

**All three states, spelled out:**

| `accent_hue` | Meaning |
|---|---|
| `null` | Use the deterministic default hue (ADR-0034) |
| `0-359` | Use this hue |
| `-1` (`NO_TOPIC_COLOR`) | Opt out -- render the palette's plain `--accent`, no `--topic-hue` set |

**`topicHue()` is the only place that interprets the sentinel.** It now returns
`number | null` instead of a bare `number`: `null` means "set no `--topic-hue`," which
every consumer already needs to handle correctly (Card.tsx's expanded border, hero
ring, `.card-topic`, saved tiles) since that's the same shape `--topic-accent`'s CSS
fallback already expects. Three call sites (`SavedView`, `LikedView`, `NotesView`'s
collection-filter chips) were reading `UserTopic.accent_hue` directly off the wire
instead of through `topicHue()` -- those are the ones a sentinel would silently break,
rendering `-1` as a red-ish hue via `oklch(from var(--accent) l c -1deg)` instead of no
color at all. They're moved onto a new `explicitTopicHue()`, which was already their
actual intent (tint only on an explicitly chosen hue, never the computed default) --
the opt-out state and "never colored, no default shown" were already indistinguishable
there before this change, and stay that way, which is correct for a chip meant to
label an actively-chosen color.

**No new picker widget.** The existing 8-swatch row in `TopicStatsModal` (ADR-0034's
"discrete swatches, not a continuous wheel" pattern) gains a 9th control: filled with
the plain `--accent` (honest -- that's exactly what selecting it renders) with a
diagonal slash overlay, the conventional "no fill" affordance distinguishing it from a
hue choice rather than looking like one more color.

## Consequences

**Easier**
- Zero schema changes; the whole feature is a validator range widen, a client-side
  sentinel constant, and a picker button.
- A user who finds mixed-feed tinting noisy can turn it off per topic without losing
  the ability to turn it back on (still stores a real value, just a specific one).

**Harder**
- `accent_hue`'s three-state meaning now lives only in code comments and this ADR, not
  in the type system -- `number | null` on the wire doesn't distinguish "a hue" from
  "the opt-out sentinel." A reviewer unfamiliar with this ADR could reasonably read
  `-1` as a bug. Mitigated by requiring every read to route through `topicHue()`/
  `explicitTopicHue()` rather than reading `accent_hue` raw, with a comment on the
  field pointing here.

## Alternatives considered

**A second boolean column (`color_enabled` or similar).** Rejected: makes the pair a
two-column invariant (a `hue` alongside an `enabled` that can disagree) for a state
that fits in the existing nullable int's unused negative range, and would have needed
a migration `set_color` and every reader don't otherwise need.

**Redefine `null` as "no color" and always materialize a real hue at subscribe time.**
The cleanest data model in isolation, but it inverts ADR-0034's whole point --
`null`'s value *is* "compute the default lazily, no write needed just to have one."
Redefining it would also mean a backfill `UPDATE` across every existing `UserTopic`
row in `spoin_db`, which CLAUDE.md gates behind the project owner's explicit approval
even framed as routine maintenance. Rejected without asking, since the sentinel
achieves the same user-facing result with no data migration at all.

## Revisit when

If a topic-level (not per-user) "no color" default is ever wanted -- e.g. an
editorially flagged topic that should never tint regardless of who's viewing --
that's a `Topic`-level field the same way ADR-0034's "Revisit when" describes for a
shared accent color, with `UserTopic.accent_hue` still taking precedence when set
(including the sentinel).
