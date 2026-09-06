# Handoff: co-designing a topic's curriculum

> Written 2026-09-06. The architecture is
> [`docs/architecture/authored-curriculum.md`](../architecture/authored-curriculum.md).
> Knowledge authoring is [`antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md)
> and images are § 10 of that same file plus
> [`next-image-sourcing.md`](next-image-sourcing.md). This document is the third delivery
> and it is deliberately last.

**A curriculum is authored, never generated.** No LLM call decides what Spoin teaches or in
what order. The curriculum file is the truth; deterministic code projects it into `Topic` and
`Subtopic` rows; the generator's only job is writing cards for a subtopic that already
exists. Getting this file right is therefore the highest-leverage authoring work in the
project — every card in the topic inherits its shape.

## The sequence, per topic

**These three steps happen in this order, per topic, and the curriculum is always third**
(owner, 2026-09-06):

```
1. KNOWLEDGE      curate the topic's corpus with the owner
                  → docs/the_spoin_universe/corpus/…
2. IMAGES         source the topic's imagery with the owner
                  → docs/the_spoin_universe/images/…
3. CURRICULUM     co-design the teaching structure with the owner
                  → docs/the_spoin_universe/curricula/…
```

The ordering is not administrative. A curriculum names the documents that back each
subtopic, so it cannot be written before those documents exist — and a subtopic's card mix
depends on what visual material the topic actually has, so it cannot be written before the
images are known. **Do not start step 3 until steps 1 and 2 are delivered and the owner has
accepted them.**

## How step 3 runs

**Propose one curriculum, not a menu.** Read the topic's corpus, then bring the owner a
single proposed structure with **brief reasoning** — why these subtopics, why this order, why
these weights. Not three options to choose between, and not a list of open questions. One
model, argued.

Then ask the owner to proceed or change it. Expect changes; the proposal is a starting point
that saves them a blank page, not a decision you are making on their behalf. Iterate until
they approve, then write the file.

**Keep the reasoning short.** A paragraph per major decision, not an essay. What the owner is
judging is the shape — the subtopic list, the order, the tier spread and the weights.

## Where the file lives

One file per topic, mirroring nothing else in the tree because a curriculum is per-topic
rather than per-subject:

```
docs/the_spoin_universe/curricula/
  rust/
    curriculum.md
  bhagavad-gita/
    curriculum.md
```

## The format

YAML front matter, no prose body. This file is data — it is parsed into its own tables and
**deliberately never chunked or embedded**, because a curriculum is teaching structure rather
than knowledge, and syllabus scaffolding must not end up in the retrieval pool where cards
could ground on it.

```markdown
---
topic: Rust
description: Systems programming with ownership, borrowing, lifetimes and fearless concurrency
is_survey: false
subtopics:
  - title: Ownership & Move Semantics
    description: Why a value has exactly one owner, and what a move actually costs
    prerequisites: []
    sources:
      - computer-science/programming-languages/rust/foundations-ownership-borrowing-and-lifetimes.md
    tiers:
      beginner:
        target_cards: 18
        card_types: { prose: 8, code: 6, comparison: 2, ascii: 2 }
      intermediate:
        target_cards: 14
        card_types: { prose: 5, code: 6, diagram: 1, ascii: 2 }
  - title: Smart Pointers (Box, Rc, Arc)
    description: Heap ownership, shared ownership, and what each pointer costs
    prerequisites: [Ownership & Move Semantics]
    sources:
      - computer-science/programming-languages/rust/memory-management-smart-pointers-and-interior-mutability.md
    tiers:
      intermediate:
        target_cards: 15
        card_types: { prose: 6, code: 7, ascii: 2 }
---
```

### Fields

| Field | Required | Notes |
|---|---|---|
| `topic` | **yes** | The canonical topic name, as a learner would say it. |
| `description` | **yes** | One sentence. Becomes `topic.description` and is seen by every generation call. |
| `is_survey` | **yes** | `true` for a tour of a field that points at narrower topics, `false` for one subject taught to bedrock ([ADR-0007](../adr/0007-curriculum-driven-generation.md)). Should agree with the `scope` on the topic's corpus documents. |
| `subtopics[].title` | **yes** | The unit a learner sees and progresses through. Stable — it is the projection's match key, so renaming one replaces it rather than editing it. |
| `subtopics[].description` | **yes** | What this subtopic covers, in one or two sentences. This is what the card writer is briefed with, so vagueness here shows up in every card. |
| `subtopics[].prerequisites` | **yes** (may be empty) | Titles of other subtopics **in this same file**. Must form a DAG. This is the ordering; document order is not. |
| `subtopics[].sources` | **yes** | Corpus paths, relative to `docs/the_spoin_universe/corpus/`, that teach this subtopic. Every path must exist. |
| `tiers` | **yes** | A map of `beginner` / `intermediate` / `advanced` → that tier's plan. Include only the tiers the subtopic should be taught at; a concept that is meaningless to a beginner simply has no `beginner` key. |
| `tiers.<t>.target_cards` | **yes** | **Must be 5–25** — the database enforces this band (`target_cards BETWEEN 5 AND 25`), so a value outside it fails validation rather than the migration. |
| `tiers.<t>.card_types` | **yes** | Quotas per card type. Must sum to `target_cards`. |

### The card-type vocabulary

Exactly these five, and a typo is a hard error rather than a silent sixth kind:

| Type | What it is |
|---|---|
| `prose` | Explanation carrying the idea in words |
| `code` | A worked code example. **Non-technical topics must use 0** — enforced outside the prompt |
| `diagram` | A mermaid diagram ([ADR-0067](../adr/0067-mermaid-diagrams-and-form-free-ascii.md)) |
| `comparison` | Myth vs fact, or A vs B ([ADR-0017](../adr/0017-card-archetypes.md)) |
| `ascii` | A curated ASCII gag scene ([ADR-0079](../adr/0079-ascii-library-is-gags-only.md), [ADR-0099](../adr/0099-ascii-scenes-carry-their-own-explanation.md)) |

**Two constraints on quotas that are worth knowing while you write them.** Every `ascii` card
consumes a curated library scene, and a scene is single-use within a topic
([ADR-0080](../adr/0080-ascii-fetcher-node.md)) — so a topic asking for more ascii cards than
the library can distinctly serve will have some fall back to free-drawing. And `code` quotas
on a non-technical topic are forced to zero regardless of what the file says, so setting one
is a mistake the validator should catch rather than a preference.

## Writing a good curriculum

**Order by dependency, not by convention.** `prerequisites` is the real ordering, and it
should encode a genuine dependency — you cannot reason about lifetimes without borrowing —
rather than the sequence a textbook happens to use.

**Weight by importance, not by uniformity.** `target_cards` is where you say what matters.
Ownership deserving 18 cards and a niche corner deserving 6 is the signal being carried; 47
subtopics at 12 cards each says nothing.

**Tier by what a learner at that level can actually use.** A subtopic present at all three
tiers is teaching three genuinely different treatments of the concept, not the same material
three times. If you cannot say what the advanced treatment adds, leave the tier out.

**Only name sources that actually teach the subtopic.** A path listed because it mentions the
term makes card grounding worse, not better.

## Checking your work

```bash
make curriculum-check
```

Pure validation — no network, no model, no database, and it reports every problem in every
file rather than stopping at the first, exactly like `make corpus-check`. It verifies:
required fields; the tier and card-type vocabularies; `target_cards` in 5–25;
`card_types` summing to `target_cards`; `prerequisites` resolving to titles in the same file;
the prerequisite graph being acyclic; and **every `sources` path existing in the corpus**.

Ask the owner to run it at the end of a delivery.

## What to hand back

Close a curriculum delivery with: the proposed structure and the reasoning behind it, what
changed after the owner's review, any subtopic you wanted to include but could not because
the corpus does not support it, and anything in this contract that turned out to be wrong or
unworkable — said in the same run rather than worked around.
