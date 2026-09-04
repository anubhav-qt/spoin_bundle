# ADR-0042: Free-form generator-drawn ASCII art, and a real hero-card mechanism

- **Status:** Accepted
- **Date:** 2026-08-20
- **Deciders:** Anubhav
- **Supersedes:** [ADR-0021](0021-ascii-scene-library.md)'s catalog-based approach (the
  library was never authored -- see Context)
- **Resolves:** [docs/tasks/0006](../tasks/0006-curated-hero-cards.md)
- **Amended by:** [ADR-0067](0067-mermaid-diagrams-and-form-free-ascii.md) -- the stickman requirement below is removed; an ASCII scene may take any form, and diagram cards moved to mermaid entirely.
- **Amended by:** [ADR-0066](0066-redraw-over-budget-ascii-art.md) -- **the "drop the
  visual, keep the card" degradation rule below no longer holds.** Over-budget art is
  redrawn, and if the redraw fails the card is **rejected outright and regenerated**,
  never published without its art. This back-reference was missing until 2026-09-05: 0066
  named 0042 but not the reverse, so a reader arriving here -- or at
  [ADR-0021](0021-ascii-scene-library.md), whose "degrades to a card with no art" language
  reads as current -- had no way to learn the rule had been replaced.

## Context

ADR-0021 decided ASCII art should be **selected** from a curated, hand-authored scene
library, never drawn by the generator -- models were judged unreliable at ASCII art, and
the quality gate has no detector for "does this look like anything." That decision was
sound given its premise, but the premise never got tested against reality: the ~40-scene
catalog it depended on was never actually authored. `CardDraft.visual_id`/`visual_slots`
have sat wired-but-unpopulated since ADR-0021 landed -- every card generated under that
design has shipped with no art at all, silently. ADR-0021's own "Revisit when" named
exactly this test as the reopening condition: "Model ASCII-art quality changes enough that
the premise of this ADR is simply false... it should be re-tested rather than assumed."

Separately, `card.is_hero` (ADR-0018) has had the same problem from the other direction:
the real mechanism was deferred to [task 0006](../tasks/0006-curated-hero-cards.md) and
never built. The generation pipeline has never once set `is_hero=true` on a real card --
only the fixture seeder's "first card listed" placeholder ever has.

A testing branch (`non-ascii-library-generation-testing`) tried the free-form generation
alternative directly, with real guardrails (a 40-column width limit enforced server-side,
dropping the visual rather than the card on violation) and a real hero mechanism (a
dedicated per-subtopic-tier prompt, issued once, before that tier's ordinary cards). The
result is being promoted to `main` as of this ADR.

## Decision

**The generator draws ASCII art directly**, in the same structured-output call that
produces `title`/`summary`/`body`, instead of selecting from a catalog:

- `ascii_label`, `ascii_art`, `ascii_alt` are new wire-level fields (`langchain_impl.py`).
  `visual_id`/`visual_slots` (schema, unchanged) now hold `ascii_label` and
  `{"art": ascii_art, "alt": ascii_alt}` respectively -- reusing the existing nullable
  columns ADR-0021 already put in place, so this needed no migration.
- **The model is still trusted for taste only, never for the constraint.** A 40-column
  width limit (the same budget ADR-0021 enforced at catalog-load time, now checked against
  freehand output) is enforced server-side in `_ascii_visual_fields()` -- a line over
  budget drops the visual and keeps the card, exactly ADR-0021's degrade-to-"no art"
  posture, never a rejected card or truncated/wrapped art.
  **Superseded for the width-violation path by [ADR-0066](0066-redraw-over-budget-ascii-art.md):**
  an over-budget drawing is now redrawn within budget and, only if that fails, the card is
  rejected whole -- the silent drop-the-visual is gone. The 40-column cap itself is
  unchanged.
- Art is instructed to be used sparingly ("most cards should have none"), and the prompt
  carries the same "weight classes in wrestling" example ADR-0021's Context used to set
  the bar for charm.
- **Rendering**: art renders first, above everything else in the card, and -- while
  collapsed -- stands in for the usual teaser/summary entirely rather than alongside it
  (`Card.tsx`'s `AsciiArt`/`hasAsciiArt`). No height cap on the art box while collapsed,
  since it IS the whole preview in that state, not an inset illustration next to a
  differently-capped teaser.

**`is_hero` is real now.** `generate_subtopic_cards` issues one dedicated call per
subtopic-tier, `want_hero=True`, `count=1`, before that tier's ordinary rounds -- but only
when the tier has no existing cards and no existing hero (`SubtopicPlan.has_hero`, a new
per-subtopic-tier query). A separate prompt (`_HERO_CARDS_SYSTEM`) teaches the model what a
hero card is (the subtopic's single most important idea, rendered larger, never collapsed)
and is used ONLY for that one call; every other card's prompt carries zero hero framing.
`is_hero` is stamped by which call produced the draft (`want_hero`), never read from the
model's own output -- unchanged "derived, never self-reported" posture, same as
`archetype`. A hero call returning more than one card (the model doesn't reliably respect
`count=1`) keeps only the first; extras are silently dropped, never persisted, never
counted as a second hero.

## Consequences

**Easier**

- Cards actually carry art now, on a subtopic that's worth it, instead of the field
  existing in schema and prompt with nothing behind it.
- `is_hero` reflects a real generation-time decision instead of "whichever card the
  fixture seeder happened to list first" -- task 0006 is done.
- No migration was needed for either change -- both reused fields ADR-0021/0018 already
  put in the schema for exactly this reason.

**Harder**

- ADR-0021's core argument (models are unreliable at ASCII art, no detector exists to
  catch a bad drawing) is not disproven, only untested at scale -- this ADR accepts that
  risk deliberately rather than resolving it. A card with a genuinely bad drawing that
  still respects the 40-column budget will ship with no detector to catch it, same gap
  ADR-0021 originally flagged.
- The two-per-topic scene-reuse cap ADR-0021 specified for a finite catalog has no
  equivalent here -- there is no catalog to exhaust, so nothing currently stops two cards
  in the same topic from drawing visually similar scenes. Not addressed by this ADR.
- A hero call that returns 0 cards (a generator failure) means that subtopic-tier simply
  never gets a hero this run -- there is no retry-until-success; a future run only retries
  if `has_hero` is still false and `existing_count` is still 0 for that tier.

## Alternatives considered

**Author the ADR-0021 catalog for real instead of abandoning it.** The actual right answer
if hand-drawn quality matters more than coverage -- rejected here only because the
authoring cost was blocking the feature indefinitely (real, unglamorous work, per ADR-0021's
own "Harder" section), and testing whether current models changed the premise was cheap by
comparison. Revisit if free-form quality proves worse than expected at scale.

**A separate curation step for `is_hero`** (human-flagged, or a distinct LLM pass over an
already-generated subtopic choosing its best card after the fact), as task 0006 originally
sketched. Rejected for now: a dedicated generation-time call is simpler to wire (no new
pipeline phase, reuses the exact same batching/retry/quota machinery every other card
generation call already has) and produces a genuinely new card written FOR the hero
framing, rather than picking the best of cards that weren't written with it in mind.

## Revisit when

- Engagement data (or just eyeballing a real corpus) shows free-form art quality is
  actually bad often enough to matter -- the detector gap above is real, not
  hypothetical, until then.
- Two topically-adjacent cards draw near-identical scenes often enough to notice -- the
  reuse-cap gap above would need an equivalent mechanism (e.g. embedding-similarity check
  against other art in the same topic).
- A hero call's low success rate (generator failures, quota exhaustion) leaves a
  meaningful fraction of subtopics without a hero long-term -- would need an explicit
  retry/backfill pass rather than relying on "the next full run happens to retry it."
