# Handoff: co-designing a topic's curriculum

> Written 2026-09-06. The architecture is
> [`docs/architecture/authored-curriculum.md`](../architecture/authored-curriculum.md).
> Knowledge authoring is [`antigravity-corpus-authoring.md`](antigravity-corpus-authoring.md)
> and images are § 10 of that same file plus
> [`next-image-sourcing.md`](next-image-sourcing.md).
>
> **Amended 2026-09-07:** this is now the SECOND delivery, not the third. Images moved
> after the curriculum so that sourcing is driven by declared needs rather than done
> blind — see "The sequence, per topic" below.

**A curriculum is authored, never generated.** No LLM call decides what Spoin teaches or in
what order. The curriculum file is the truth; deterministic code projects it into `Topic` and
`Subtopic` rows; the generator's only job is writing cards for a subtopic that already
exists. Getting this file right is therefore the highest-leverage authoring work in the
project — every card in the topic inherits its shape.

## The sequence, per topic

**These three steps happen in this order, per topic** (owner, 2026-09-07 — this
**reverses** steps 2 and 3 as they stood on 2026-09-06):

```
1. KNOWLEDGE      curate the topic's corpus with the owner
                  → docs/the_spoin_universe/corpus/…
2. CURRICULUM     co-design the teaching structure with the owner, and declare
                  each subtopic's IMAGE NEEDS as part of it
                  → docs/the_spoin_universe/curricula/…
3. IMAGES         source imagery AGAINST those declared needs
                  → docs/the_spoin_universe/images/…
```

The ordering is not administrative, and it changed for a measured reason.

A curriculum names the documents that back each subtopic, so it still cannot be written
before those documents exist — step 1 stays first. But sourcing images **before** the
curriculum means sourcing them blind: you know the subject, not which ideas will be
taught. Astronomy was sourced that way and produced 76 photographs against 91 image
cards, of which roughly one in seven was defensible — a Venus radar map on a card about
Mercury's atmosphere, a nebula on a card about elliptical-galaxy classification. The
photographs were fine. They were answers to a question nobody had asked yet.

[ADR-0105](../adr/0105-the-photograph-is-chosen-before-the-card.md) fixed the runtime half
of this: a photograph is now **reserved for a subtopic before the card is written**, and the
card is written about the picture. That makes relevance true by construction — but only
over whatever the catalog happens to hold. **This step ordering is the authoring half:** if
the curriculum is written first, the image sourcing knows exactly which subtopics need
pictures and what those pictures have to show, so the catalog is built to answer real
questions instead of being searched in the hope that it can.

**Do not start step 3 until step 2 is delivered and the owner has accepted it.** Step 2's
deliverable now includes the image needs — see below.

## How step 2 runs

**Propose one curriculum, not a menu.** Read the topic's corpus, then bring the owner a
single proposed structure with **brief reasoning** — why these subtopics, why this order, why
these weights. Not three options to choose between, and not a list of open questions. One
model, argued.

Then ask the owner to proceed or change it. Expect changes; the proposal is a starting point
that saves them a blank page, not a decision you are making on their behalf. Iterate until
they approve, then write the file.

**Keep the reasoning short.** A paragraph per major decision, not an essay. What the owner is
judging is the shape — the subtopic list, the order, the tier spread and the weights.

### The curriculum is also the image brief

Every tier that asks for `image` cards **must say what those pictures have to show**, in
`image_needs`. That list is what step 3 goes shopping with, and it is the deliverable that
makes the reordering worth anything: a sourcing pass told "astronomy, 60–80 pictures"
returns a general-interest gallery, while one told "a resolved Type Ia supernova in its host
galaxy; a full-sky CMB anisotropy map; Saturn's rings edge-on showing the Cassini division"
returns a catalog that answers the curriculum.

Write each need as **the photograph, not the concept** — what a camera could actually
capture. This is the discipline that stops the catalog filling up with pictures of things
that cannot be photographed:

> **Good:** "a globular cluster resolved into individual stars"
> **Good:** "a limb-on view of a planet's atmosphere against space"
> **Bad:** "the Eddington luminosity limit" — no photograph shows a limit
> **Bad:** "the Sachs-Wolfe effect" — an inference from a map, not a sight

**If a tier's ideas are mostly unphotographable, say so and lower the `image` quota.** That
is the correct outcome, not a failure to try hard enough. An `image` quota with no
corresponding real photograph used to produce a confidently wrong picture; under
[ADR-0105](../adr/0105-the-photograph-is-chosen-before-the-card.md) it produces a prose card
instead, which is better but is still a quota that lied. Ask for the number of pictures the
subject can actually supply.

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
scope: topic
subtopics:
  - title: Ownership & Move Semantics
    description: Why a value has exactly one owner, and what a move actually costs
    prerequisites: []
    tiers:
      beginner:
        target_cards: 16
        card_types: { prose: 5, code: 4, ascii: 4, diagram: 2, comparison: 1 }
        grounding:
          - "computer-science/programming-languages/rust/foundations.md#Ownership and Move Semantics"
          - "computer-science/programming-languages/rust/foundations.md#The Borrow Checker: Shared vs Exclusive Borrows"
          - "computer-science/programming-languages/rust/tips-and-tricks.md#Common Borrow Checker Mistakes"
      intermediate:
        target_cards: 18
        card_types: { prose: 5, code: 5, ascii: 4, diagram: 2, comparison: 1, image: 1 }
        # What a camera would capture, one line per image card. Step 3 sources
        # against exactly this list (ADR-0105).
        image_needs:
          - "a stack-and-heap memory diagram photographed from a whiteboard"
        grounding:
          - "computer-science/programming-languages/rust/foundations.md#Lifetimes: Annotations and Elision Rules"
          - "computer-science/programming-languages/rust/foundations.md#Reborrowing Mechanics and Split Borrows"
  - title: Smart Pointers (Box, Rc, Arc)
    description: Heap ownership, shared ownership, and what each pointer costs
    prerequisites: [Ownership & Move Semantics]
    tiers:
      intermediate:
        target_cards: 15
        card_types: { prose: 5, code: 4, ascii: 4, diagram: 1, comparison: 1 }
        grounding:
          - "computer-science/programming-languages/rust/memory-management.md#Heap Allocation with Box"
          - "computer-science/programming-languages/rust/memory-management.md#Shared Ownership with Rc and Arc"
          - "computer-science/programming-languages/rust/memory-management.md#Interior Mutability: RefCell and Mutex"
---
```

### Fields

| Field | Required | Notes |
|---|---|---|
| `topic` | **yes** | The canonical topic name, as a learner would say it. |
| `description` | **yes** | One sentence. Becomes `topic.description` and is seen by every generation call. |
| `scope` | **yes** | `survey` for a tour of a field that points at narrower topics, `topic` for one subject taught to bedrock across tiers ([ADR-0007](../adr/0007-curriculum-driven-generation.md)), `one_shot` for one subject taught once, easy to advanced ([procedure.md](../the_spoin_universe/procedure.md#survey-topic-or-one-shot--the-distinction-that-changes-your-research)). Only `topic` keeps three tiers ([ADR-0106](../adr/0106-typescript-on-hono-and-the-authoring-harness.md)). Must agree with the `scope` on the topic's corpus documents. `is_survey` was replaced by this and now fails validation. |
| `subtopics[].title` | **yes** | The unit a learner sees and progresses through. Stable — it is the projection's match key, so renaming one replaces it rather than editing it. |
| `subtopics[].description` | **yes** | What this subtopic covers, in one or two sentences. This is what the card writer is briefed with, so vagueness here shows up in every card. |
| `subtopics[].prerequisites` | **yes** (may be empty) | Titles of other subtopics **in this same file**. Must form a DAG. This is the ordering; document order is not. |
| `tiers` | **yes** | A map of `beginner` / `intermediate` / `advanced` → that tier's plan. Include only the tiers the subtopic should be taught at; a concept that is meaningless to a beginner simply has no `beginner` key. |
| `tiers.<t>.target_cards` | **yes** | **Must be 5–25** — the database enforces this band (`target_cards BETWEEN 5 AND 25`), so a value outside it fails validation rather than the migration. |
| `tiers.<t>.card_types` | **yes** | Quotas per card type. Must sum to `target_cards`. |
| `tiers.<t>.image_needs` | **yes when `card_types.image > 0`** | One line per photograph the tier needs, describing **what a camera would capture**, not the concept. This is the brief step 3 sources against ([ADR-0105](../adr/0105-the-photograph-is-chosen-before-the-card.md)). Length should match the `image` quota. Omit entirely when the quota is 0. |
| `tiers.<t>.grounding` | **yes** | List of section-level corpus anchors: `"<corpus_path>#<exact ## heading>"`. Quote every entry because headings with colons `:` break YAML parsing otherwise. 5–10 sections per tier. |

### The card-type vocabulary

Exactly these six, and a typo is a hard error:

| Type | What it is | Quota Guideline (Photographic / Observational) | Quota Guideline (Pure Code & Theory) |
|---|---|---|---|
| **`prose`** | Explanation carrying the idea in words | **Strictly 25–30% max** (4–6 cards). Hard ceiling — never exceed 30% to prevent text walls in the feed. | **Strictly 25–30% max** (4–6 cards). Kept tight; code and diagrams carry the weight. |
| **`image`** | A card anchored by a verified photographic asset from the open-licensed catalog ([ADR-0095](../adr/0095-open-licensed-image-catalog.md), [ADR-0105](../adr/0105-the-photograph-is-chosen-before-the-card.md)). The photograph is reserved for the subtopic **before** the card is written, and the card is written about it. | **2–3 per tier** (~12–18%), and **only as many as the tier can name real `image_needs` for.** The old rule here was to match the count of images already sourced; that is now backwards — the quota and its `image_needs` are written FIRST and the sourcing answers them. A tier whose ideas cannot be photographed gets a lower quota, not a hopeful one. | **Strictly 0** (pure code/theory manifests are strictly empty `images: []`). |
| **`code`** | A worked code example | **Strictly 0** for non-technical topics (enforced outside prompt). | **4–6 cards per tier** (~25%). Primary worked examples. |
| **`diagram`** | A mermaid diagram ([ADR-0067](../adr/0067-mermaid-diagrams-and-form-free-ascii.md)) | **2–3 per tier** (~10–15%). Reserved strictly for things photos cannot show. | **2–4 per tier** (~15–20%). Primary visual anchor. |
| **`comparison`** | Myth vs fact, or A vs B ([ADR-0017](../adr/0017-card-archetypes.md)) | **4–6 per tier** (~25–30%). High density from `tips-and-tricks.md` misconceptions. | **2–3 per tier** (~10–15%). Architectural trade-offs. |
| **`ascii`** | A curated ASCII gag scene ([ADR-0079](../adr/0079-ascii-library-is-gags-only.md)) | **3–5 per tier** (~20–25%). Curated gags learners screenshot. | **4–5 per tier** (~20–25%). Aggressively breaks up code/text walls. |


**`image_needs` is NOT validated.** `frog.curriculum.contract` reads the keys it projects
into the database and ignores everything else, so a misspelled `image_needs`, a missing one
on a tier with a non-zero `image` quota, or a list whose length disagrees with that quota all
pass `make curriculum-check` in silence. It is an authoring-side field consumed by the image
sourcing pass, not by the projection — treat it as your own discipline, exactly like the
`code`-on-a-non-technical-topic case below. If it starts going wrong in practice, the fix is
a check in the contract, not a firmer sentence here.

**Two constraints on quotas that are worth knowing while you write them.** Every `ascii` card
consumes a curated library scene, and a scene is single-use within a topic
([ADR-0080](../adr/0080-ascii-fetcher-node.md)) — so a topic asking for more ascii cards than
the library can distinctly serve will have the surplus **written as prose cards instead**
([ADR-0104](../adr/0104-the-library-owns-the-drawing.md) deleted the free-draw fallback;
the model no longer draws anything, ever). And `code` quotas
on a non-technical topic are forced to zero downstream regardless of what the file says
(enforced outside the prompt) — `make curriculum-check` does **not** catch a stray `code`
quota, because the format carries no technical/non-technical flag for it to judge against,
so treat a non-zero `code` quota on a non-technical topic as a mistake even though
validation stays silent about it.

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

**Photographic subjects lean on `image`.** For observational topics (Tier 1 & 2), cards typed
as `image` are anchored by genuine photographs from the verified catalog (`images.md`). Their
descriptions serve as dense semantic retrieval bait so the model grounds explanations in
physical morphology, color palettes, and observable structures. Quotas of 2–3 `image` cards
per tier ensure full coverage of all sourced visual anchors across the curriculum.

**Code and theory subjects lean on `diagram`.** Canon
(`_canon/card-archetypes-and-content-shapes.md`) sets this: subjects with no photographic
imagery — Rust, backend, systems, generative AI — compensate with a significantly higher
density of mermaid `diagram` cards, which become their primary visual anchor. Architectures,
state machines, memory layouts, parse trees, concurrent pipelines and protocol handshakes are
what those quotas are for. The quota is where that rule takes effect, because nothing
downstream chooses the mix.

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
