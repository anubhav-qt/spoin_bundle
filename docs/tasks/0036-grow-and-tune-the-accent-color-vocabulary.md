# Task 0036: Grow and tune the accent-colour vocabulary

**Owner:** Anubhav (curatorial / human-judgment, same reason as [Task 0033](0033-grow-the-curated-ascii-library-over-time.md))
**Blocked on:** nothing — [ADR-0075](../adr/0075-embedding-derived-topic-accent-color.md)
shipped a first vocabulary. This is the standing "make it better" follow-up.
**Timebox:** none — long-horizon, revisited in small batches.

## The problem

ADR-0075 picks a topic's default accent hue by embedding-similarity between the
topic and a curated colour vocabulary: `apps/api/src/spoin/topics/accent_color_data/colors.json`,
~250 `{name, hue}` entries. The *distinctness* of the result is enforced by angle
arithmetic and does not depend on the vocabulary. The *aptness* — whether a
marine-biology topic actually leans blue-green rather than landing on "mustard" —
depends entirely on this list: how many names there are, how evocative of a
domain each one is, and whether the hue attached to each name is right.

The initial list was written in one sitting by Claude, spread roughly evenly
around the wheel, with domain-suggestive names where they were easy to think of
("ocean", "moss", "rust", "blueprint", "parchment"). It has not been checked
against real topic embeddings, and the owner has not eyeballed the hues.

## What to do, in small batches

- **Verify the shipped hues.** For each entry, is `hue` actually where that
  colour sits on an OKLCH/HSL wheel? A handful were estimated. `--topic-accent`
  derives lightness/chroma from the active palette (ADR-0034), so only the hue
  angle matters, but a wrong angle sends a topic to the wrong colour family.
- **Widen domain coverage.** Add names that pull common topic areas toward a
  sensible colour: sciences, humanities, crafts, sports, languages, business,
  health. The test for a good addition is "would a topic in this area embed close
  to this word?", not "is this a colour name people know".
- **Prune near-duplicates** that add embedding mass without adding a distinct
  hue or a distinct association.
- **Spot-check against real embeddings** once fastembed is the resolved embedder
  in a dev environment: embed a dozen real topic names, print the top-5 nearest
  vocabulary entries for each, sanity-check the leaders.
- Keep the 40°-bucket spread invariant (`test_accent_color.test_shipped_vocabulary_is_well_formed`)
  — every bucket populated — so the fallback surface stays even.

## Not in scope

The assignment algorithm, the distance filter, the degradation path, and the
`UserTopic.accent_hue` storage are all settled by ADR-0075. This task is the data
file only.
