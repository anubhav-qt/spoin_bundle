# ADR-0021: ASCII art from a curated scene library, not from the generator

- **Status:** Superseded by [ADR-0042](0042-freeform-ascii-and-real-hero-mechanism.md) --
  the catalog this ADR depends on was never authored, so this decision's premise went
  untested for the entire time it was nominally in effect. ADR-0042 has the generator
  draw art directly instead, with the width/degradation guarantees below re-enforced
  server-side against freehand output rather than a catalog. Kept here, not edited, per
  this repo's "don't edit history" rule.
- ⚠️ **The degradation rule below is doubly stale.** Every "degrades to a card with no
  art" / "keeps the card, strips the visual" guarantee in this document was replaced by
  [ADR-0066](0066-redraw-over-budget-ascii-art.md): a visual that cannot be made valid
  now **rejects its card for regeneration** rather than publishing it art-less. Read
  0042 and 0066 before quoting anything below — this note exists because a session in
  2026-09-05 quoted this ADR's degrade language as current policy.
- **Amends:** [ADR-0017](0017-card-archetypes.md) (adds `ascii` to the archetype set)
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

A stack of title + summary cards, even with the archetype-varied teasers from
[ADR-0017](0017-card-archetypes.md), still reads as text all the way down. We want cards
that stop a scroll and are worth screenshotting -- a silly stickman delivering a real fact, or
a two-panel scene that _shows_ a concept rather than describing it. The canonical example:
weight classes in wrestling, panel one two stick figures facing off, panel two the heavy
one sitting on the light one, who says "shouldn't have done this".

The obvious implementation -- ask the generator to draw the art -- does not survive contact
with two facts about this system:

1. **Models are unreliable at ASCII art.** Line-art rendered as a character grid is a
   spatial task expressed in a token stream. Asking for a specific scene returns something
   recognizable a minority of the time; the rest is a smear of slashes that reads as
   broken rather than as charming.
2. **Our quality gate cannot catch the failure.** The gate
   (content-model.md, "Quality gate") is near-duplicate embedding comparison, topic
   conformance, an independent difficulty re-rating, and a factual-accuracy pass -- all of
   them operating on _text as meaning_. None of them can tell whether a grid of characters
   looks like anything. We would be adding a content dimension with no detector, into a
   **shared** corpus, which is the failure shape ADR-0007 and the gate exist to prevent.

Two smaller constraints that also kill free-form generation:

- **Width.** A phone renders roughly 38-42 monospace columns. Models do not reliably
  respect a column budget, and ASCII art that wraps is unrecoverable -- not degraded,
  destroyed.
- **It is not prose.** Art in `body` inherits the reader's prose font, prose line-height,
  and prose wrapping, all three of which break it.

## Decision

**Art is retrieved, not generated.** We ship a curated library of ASCII scenes. The
generator's job is selection and dialogue, never drawing.

### The scene library

A version-controlled catalog of hand-authored scenes (target ~40 at launch), living as
data in the API package rather than in the database -- it is content we author and review,
not content the system produces.

Each scene declares:

```
scene
  id              stable key, e.g. "sit-on-guy"
  description     one line, written FOR THE MODEL: what the scene depicts and
                  what kind of idea it fits
  panels[]        raw ASCII, one or more, with {{slot}} placeholders
  slots[]         name, max_chars, which panel it sits in
  width           max column count across all panels
```

Every scene is authored inside a **40-column budget**, checked at catalog-load time. The
budget is a property of the library, not a hope about the model.

### What the generator does

In the same structured-output call that produces `title`/`summary`/`body`, the model may
additionally return a `visual_id` (a key from the catalog, whose `description` list is
supplied in the prompt) and the text for that scene's slots. It never returns art.

This is a task models are actually good at -- pick the fitting item from a described list,
write a one-line joke that lands -- and it inherits the batching economics of
[ADR-0005](0005-batch-llm-calls.md) for free: no extra request, just extra fields.

### Card schema

```
card
  visual_id       str, null      key into the scene catalog
  visual_slots    jsonb, null    {slot_name: text}
```

The card stores a **reference plus text**, never rendered art. Consequence worth stating
plainly: fixing a scene's drawing improves every card that uses it, retroactively, with no
regeneration and no new `version` rows.

### Three deterministic rules, enforced server-side

The model is trusted for taste, never for constraints:

1. **Slot text over `max_chars` is rejected.** The card keeps its text and loses its
   visual; we do not reject a good card over a long punchline, and we never render
   overflow.
2. **A `visual_id` not in the catalog is dropped.** Same fallback.
3. **A scene may appear on at most two active cards within a topic.** Checked by
   counting active cards in the topic at insert/activation time -- _not_ trusted to the
   prompt. The model generates in batches of ~10 and cannot see the rest of the corpus,
   which is exactly the reasoning behind requiring intra-batch dedup on top of
   corpus dedup (content-model.md, "Near-duplicate detection"). The third and later
   use has its visual stripped, keeping the card.

Every one of these degrades to "a card with no art", never to "a broken card".

### Rendering and density

- Art renders in a dedicated monospace box owned by the renderer, at a locked font, with
  horizontal overflow impossible by construction. It is **not** markdown inside `body`.
  This is what makes [ADR-0023](0023-reader-font-selection.md)'s user-selectable prose
  font safe.
- `ascii` joins the derived `archetype` set (ADR-0017), derived trivially from
  `visual_id is not null`. It stays consistent with that ADR's rule: derived, never
  self-reported.
- Art is expected **primarily on hero cards** -- the one-per-subtopic anchors of
  [ADR-0018](0018-hero-mechanism-and-teaser-refinements.md) -- not uniformly. A joke
  format used on all ~750 cards of a topic is not a joke format, it is a layout.

### Accessibility

Every scene carries authored alt text (a property of the scene, not of the card), so a
screen reader gets a sentence rather than a character grid.

## Consequences

**Easier**

- Art quality is decided once per scene by a human, instead of ~750 times per topic by a
  model with no reviewer.
- Width safety, monospace rendering, and alt text are structural rather than prompted.
- Improving art is a data edit, not a regeneration run.

**Harder**

- Somebody has to draw ~40 scenes. This is real, unglamorous authoring work and it
  gates the feature; there is no version of this ADR where the art appears for free.
- A fixed catalog is inherently less specific than bespoke art. Some concepts will get a
  scene that _nearly_ fits, and the honest options are to accept the near-fit, add a
  scene, or ship the card without art. It must never be "let the model draw this one".
- The catalog description list occupies prompt space in every generation call, growing
  with the library.
- The two-per-topic cap means a broad topic can exhaust well-fitting scenes and get
  progressively worse matches. That is a deliberate trade against repetition, and the
  right response is more scenes, not a higher cap.

## Alternatives considered

**Let the generator draw the art, gate it with a vision model.** Rejected on cost and on
honesty: it adds a per-card cloud request to a project whose entire generation economics
(ADR-0003, ADR-0005) rest on one request validating twenty cards -- and "does this look
like a fat stickman" is a judgment we would then be trusting a model to make about
another model's spatial output, with no ground truth.

**Generate art freely and eyeball a sample.** Rejected -- this is the trap. Five
hand-checked cards look fine; the failures land in the other 745 where nobody looks.
Shared corpus, no detector.

**Store rendered art on the card instead of a `visual_id` reference.** Rejected: it
freezes every drawing at generation time, so fixing a scene means a regeneration pass and
new `version` rows for a change that has nothing to do with the card's content.

**Put the art in `body` as a fenced block.** Rejected -- it inherits prose typography and
wrapping, and it makes width a text-generation problem again rather than a layout one.

**No cap on scene reuse, rely on the prompt to vary.** Rejected for the batching reason
above: a model generating ten cards cannot know what the other seventy-four already used.

## Revisit when

- The library is large enough, or a topic broad enough, that the two-per-topic cap starts
  stripping visuals from cards that would benefit -- the signal to grow the catalog or
  reconsider the cap.
- Engagement data shows art-bearing cards are _not_ outperforming plain ones, which would
  mean the authoring cost is buying charm we like and users don't.
- Model ASCII-art quality changes enough that the premise of this ADR is simply false. It
  is a claim about capability, not a principle, and it should be re-tested rather than
  assumed.
