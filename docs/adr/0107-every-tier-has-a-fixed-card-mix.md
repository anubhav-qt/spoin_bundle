# ADR-0107: Every tier has a fixed card mix, and only its ascii half carries art

- **Status:** Accepted
- **Date:** 2026-10-13
- **Deciders:** Anubhav
- **Supersedes:** [ADR-0079](0079-ascii-library-is-gags-only.md)'s "every ASCII card is a joke",
  and the old curriculum canon's free quotas with prose capped at 30% of a tier (task 0045)
- **Related:** [ADR-0099](0099-ascii-scenes-carry-their-own-explanation.md),
  [ADR-0106](0106-typescript-on-hono-and-the-authoring-harness.md),
  [harness-tools.md](../architecture/harness-tools.md)

## Context

The curriculum writer picked each tier's card types itself, within the old canon's one rule:
prose at most 30% of a tier. Every ASCII card was a gag (ADR-0079), and designer_toad drew art
for every accepted card, so a tier's cards went live only with its last piece of art. In the
first harness run that made art the slowest step: 30 cards needed 30 pieces before anything
went live, and the feed's look varied with whatever mix the writer chose.

## Decision

Every tier has the same mix, each share of its target rounded so they sum to it (the largest
remainders take the cards left over):

| Type | Share |
|---|---|
| ascii | 50%: gags 30% of the tier, small informative drawings 20% |
| diagram | 20%, each a mermaid flowchart drawn black on white, with no styling |
| prose | 20%; on a code subject any part of it may be code cards |
| comparison | 10%, myth against fact |

No image cards until photographs are sourced. Only the ascii cards carry art: each asks for a
gag or an informative drawing, within the tier's numbers for each. A card without art waits for
no drawing, so a tier goes live once no accepted card is waiting for art. A card can hold more
than its form, and still counts as its form: on a code subject an ascii card with a code block is
an ascii card. Code checks all of it: `write_curriculum` refuses a tier off the mix, and
`write_cards` refuses an ascii card without an art request, a kind of art over its quota, a
diagram card that isn't a flowchart, and mermaid styling.

## Consequences

- Half of every tier goes live without designer_toad, which halves the art each tier waits on.
- Every tier reads the same in the feed: half drawings, a fifth flowcharts, a tenth myths.
- The writer can no longer give a tier more prose or more diagrams when its subject wants
  them; a concept that suits neither form must still fill its type's share.
- A myth-against-fact card needs a real misconception, so a tier with none to hand must still
  find a tenth of its cards' worth.

## Alternatives considered

- **Keep the writer's free choice under the 30% prose cap.** It let the mix drift tier by tier,
  and every card still waited on art.
- **Art on every card, gags and informative drawings.** Keeps the look of an all-art feed, but
  leaves the art step as slow as before.
- **Code cards as their own share.** A subject without code would have to give it to another
  type; taking code out of the prose share keeps one mix for every subject.

## Revisit when

Photographs are sourced and image cards return, or the run shows a tier type (most likely
comparison) refused or rejected far more often than the others.
