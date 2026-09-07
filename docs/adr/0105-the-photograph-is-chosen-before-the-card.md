# ADR-0105: The photograph is chosen before the card, and the card is written about it

- **Status:** Accepted (inverts 0095's retrieval direction; retires 0102's planner ceiling for generation)
- **Date:** 2026-09-07
- **Deciders:** owner, Claude

## Context

[ADR-0095](0095-open-licensed-image-catalog.md) assigns images **server-side,
after drafting**, by querying the catalog with the finished card's own text.
[ADR-0102](0102-image-card-assignment-and-planner-ceiling.md) added a planner
ceiling and a `image_similarity_floor` on top. Measured against `spoin_db_2` on
2026-09-07, that arrangement produces images that are not about the cards they
sit beside:

| Card | Image it got | |
|---|---|---|
| The Phillips Relation / Type Ia Supernovae | SN 1994D | ✅ |
| Elliptical Galaxy Classification E0–E7 | Cat's Eye **Nebula** | ❌ wrong class of object |
| Mercury's Atmospheric Loss | **Venus** radar map | ❌ wrong planet |
| Kepler's Law of Ellipses: Eccentricity | Earthrise from Apollo 8 | ❌ |
| The Eddington Luminosity Limit | SN 1994D | ❌ |
| Cepheid metallicity corrections → H₀ | SN 1994D | ❌ |
| Photon Decoupling / Last Scattering | galaxy GN-z11 | ❌ |

Roughly one or two in fourteen are defensible. SN 1994D appears three times in a
random draw of fourteen.

Three compounding causes, and only the first is a bug:

1. **`image_similarity_floor` is `0.0`.** Its own comment says *"Initial
   calibration run sets this to 0.0 so all candidate similarity scores are
   recorded without rejecting drafts."* The calibration run happened; nobody
   turned it back on. Every image card accepted its top-1 neighbour no matter
   how bad.

2. **The catalog is 76 photographs, all category `astronomy`, against 91 image
   cards.** Uniqueness is per-topic, so the pool only shrinks as a tier goes on:
   the last image card in a topic picks from whatever is left.

3. **Most of what the corpus teaches has no photograph anywhere.** The
   Integrated Sachs-Wolfe effect, the photon-to-baryon ratio, Eddington's limit,
   metallicity corrections — these are quantitative relationships. No picture
   depicts them. Cosine similarity between an abstract explanation and a photo
   caption is then dominated by shared astronomy vocabulary, not by depiction,
   which is exactly why "Eddington luminosity" lands on a supernova photo: both
   are lexically about bright exploding things.

Cause 3 is the one that matters, because it means **no floor and no larger
catalog fully fixes the post-hoc direction.** Searching for a picture of a card
that has already been written is a search for something the catalog frequently
does not contain, and a top-1 query always returns *something*.

## Decision

**Reserve the photograph first, then write the card about it.**

- `reserve_images_for_plans` runs in the planning phase, beside the ASCII fetch
  and for the same reason. It queries the catalog with the **subtopic** (no card
  text exists yet, which is the point), takes the best `N` in scope, and attaches
  one `ReservedImage` to each planned image brief.
- The brief hands the writer the photograph's **`description`** — the catalog's
  own several-hundred-character scene inventory — and instructs it to teach the
  concept the picture shows, without describing or referring to the picture.
- The image is stamped onto the draft from the reservation. `assign_images` and
  `image_similarity_floor` survive only for the **repair** flow, which is
  genuinely retrofitting an image onto a card that already exists.
- **No similarity floor on the reservation.** A floor exists to judge whether a
  photograph is good enough for a card already written; here the card is not
  written yet, so any photograph in scope is one a good card can be written
  about. Scores are still recorded — a subtopic whose best available image
  scores near zero says the catalog does not cover it.
- An image brief that cannot reserve one becomes a **prose** brief, exactly as
  an unmatched ascii brief does (ADR-0104). This retires ADR-0102's planner
  ceiling for the generation path: a card can no longer be planned as an image
  card and then find no image, so there is nothing for the ceiling to prevent.

This is the same move as ADR-0104, applied to the other asset: make the asset's
relevance **true by construction** rather than hoped for from a similarity
score.

## Consequences

**Easier.** An image card cannot be irrelevant to its picture — there is no gap
left for a score to fall through. The uncalibrated-floor problem disappears
rather than needing task 0042 to land first. Retrieval quality now degrades
gracefully: a thin catalog reserves fewer cards instead of reserving bad ones.
One retrieval per tier replaces one per card.

**Harder.** The catalog now shapes the curriculum rather than decorating it: an
image card teaches what there is a picture of. That is a real editorial
constraint, and it is the honest one — the alternative was pretending to
illustrate concepts that cannot be photographed. A thin catalog now shows up as
*fewer image cards*, which is more visible than the old failure and much better
than it.

**Committed to.** Growing the catalog is now the lever for image-card volume,
and it should be grown as **depiction coverage** (objects, morphology,
instruments, surfaces) rather than subject coverage. Task 0040 gains that
framing.

## Alternatives considered

**Just set the floor and grow the catalog** — the obvious minimal fix, and the
owner's first framing. It fixes causes 1 and 2 and leaves cause 3 untouched: at
5,000 astronomy photographs, "the Sachs-Wolfe effect" still has no picture, and
the cards that most want illustrating remain the ones that cannot be. It also
spends a rejected-and-regenerated card (ADR-0066) on every miss.

**Plan image cards only for inherently visual concepts.** A good idea and
partially subsumed here — the reservation *is* that filter, applied by what the
catalog actually holds rather than by a model's judgement about what is
photographable. Worth revisiting as an explicit planner rule if reserved images
turn out to be relevant but dull.

**Match on `canonical_title` alone** instead of the full card text, to stop the
signal drowning in 1,200 characters of explanation. A real improvement to the
post-hoc direction, and it would have helped; it does not address cause 3, so it
is now moot for generation. It remains the right change for `assign_images` in
the repair flow if that path is ever measured and found wanting.

## Revisit when

The catalog is large and diverse enough that a post-hoc search would usually
find a genuinely depictive match — the signal is the reservation's recorded
scores clustering high across many subtopics rather than a handful. At that
point briefing the writer with the picture may be constraining cards that could
have been written freely.

Also revisit if image cards start reading as **captions** — if writing "about"
the photograph makes the cards describe scenery instead of teaching. The prompt
already forbids referring to the picture; if that turns out not to be enough,
the brief should carry the concept and the picture separately rather than
fusing them.
