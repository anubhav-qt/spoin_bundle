# ADR-0007: Curriculum-driven generation with a bounded, completable corpus

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav, Mayank
- **Amends:** [ADR-0006](0006-demand-driven-pool-fill.md) (lock key and starvation signal)

## Context

ADR-0005 established that we generate cards in batches. That leaves open the question of
*what* each batch should be about, and how we avoid generating the same card twice.

The naive answer is detection: generate freely, then reject near-duplicates at the quality
gate. Under a free tier this is expensive in the worst possible way, because **a rejected
card is a wasted request against our scarcest resource**. A 30% duplicate rate silently
costs 30% of daily capacity.

A first improvement is prevention: send the LLM the titles of existing cards so it avoids
repeating them. Better, but limited. Titles are a lossy proxy for content ("How Kubernetes
schedules pods" and "The kube-scheduler explained" are the same card), negative constraints
over long lists are among the weaker things LLMs do, and the list grows unboundedly.

The deeper problem: avoiding duplicates is a **weak goal**. It permits a corpus of fifty
cards about one corner of a subject, all phrased differently. What the product needs is
*coverage*.

## Decision

**Generate a curriculum per topic once. Generate cards against uncovered curriculum slots.**

```
topic
  └── subtopic          generated once per topic, cached indefinitely
        └── cards       per difficulty
```

### The curriculum pass

One "road to mastery" request per topic produces the full subtopic breakdown across all
three difficulties in a single call, so the model can lay out a coherent progression rather
than three disconnected lists. For each subtopic it also proposes a card count.

```
subtopic
  id
  topic_id
  difficulty        beginner | intermediate | advanced
  title
  description       what this subtopic covers; feeds the generation prompt
  target_cards      planner's ideal count (ceiling + priority weight)
  min_cards         threshold at which this subtopic counts as covered
  position          ordering hint within the topic
  created_at
```

Generation then targets **a specific subtopic**, which converts a negative constraint
("avoid these 200 titles") into a positive one ("write about pod scheduling"). LLMs are
substantially more reliable when pointed at a target than when avoiding a list.

### The bound is a card budget per topic

Bounding cards-per-subtopic alone bounds nothing: total cards is
`subtopics x 3 x cards_per_subtopic`, so constraining the last term simply relocates the
growth into the first. **The budget is therefore set on the total**, and the planner
distributes within it.

The budget is derived from completability rather than picked:

| Step | Value |
|---|---|
| A difficulty tier should take 5-10 sessions to finish | product requirement |
| At ~30 cards per session | **~200-300 cards per tier** |
| x 3 tiers | **~750 cards per topic** |
| at ~15 cards per subtopic | **~15-20 subtopics per tier** |

~750 cards is ~75 requests per topic at batch-of-10, which is affordable on a free tier.

The planner is therefore instructed: *you have ~750 cards for this topic, 5-25 per
subtopic, allocate them.* Both factors are constrained by one number that traces back to
a product requirement.

### Two self-correcting rules, at two levels

1. **Subtopic too large** (planner wants >25 cards): the subtopic is too broad, decompose
   it. This keeps subtopics atomic and title lists small (~20 entries), which is what makes
   the attention argument robust rather than marginal.
2. **Topic too large** (planner wants >~20 subtopics per tier): the topic becomes a
   **tour**, and the curriculum pass additionally emits the deeper sibling topics it
   introduces. The broad topic is *not* deleted or split out of existence.

Rule 2 is **generative, not destructive.** "Mathematics" remains a real, subscribable
topic that gives a genuinely good tour. Its curriculum call returns two things:

```
survey curriculum   ~750 cards, the tour itself
deep_dive topics    the siblings it introduces (Linear Algebra, Calculus, Probability...)
```

The tour's completion state then becomes a **discovery surface**: *"You've toured
Mathematics. Go deeper: Linear Algebra, Calculus, Probability."* Finish a topic, get
pointed at three more, subscribe, repeat. The completion state does real product work
rather than being a terminal badge.

Deep-dive topics are created as canonical topics immediately, **without curricula** until
someone subscribes (curricula are generated lazily on first subscription). This seeds the
topic graph, and it helps [ADR-0004](0004-topic-canonicalization.md): a user later typing
"linear algebra" matches an existing canonical topic instead of minting a new one.

**The relation is a flat edge, not a tree:**

```
topic_edge(from_topic_id, to_topic_id, kind='deep_dive')
```

A parent/child hierarchy would rebuild the unbounded-nesting problem one level up. Edges
are for discovery only; they carry no curriculum or completion semantics.

### Depth is fixed at two levels

Recursive decomposition (subtopic -> sub-subtopic -> ...) is deliberately rejected:

- It bounds nothing. Unbounded depth is unbounded breadth in disguise.
- It makes completion, the difficulty mix, and progress display substantially harder.
  "3 of 5 sub-branches of 2 of 7 subtopics" is not a usable progress indicator.
- Two levels plus topic-splitting covers every real case.

**Principle: depth is fixed at two levels; breadth is handled by splitting topics, which
users control through subscription.**

### Consequence: broad topics get survey curricula

A broad topic now receives a **survey**, not an exhaustive treatment. "Mathematics" gets a
genuinely good tour within ~750 cards. It does not make you a mathematician and must not
claim to.

*"Mathematics" is a tour; "Linear Algebra" is a course.*

The completion copy must match: "you've covered the essentials of Mathematics", with the
`deep_dive` edges offered as the next step. This is an honest completion state and the
primary route into further topic subscriptions.

Interaction with [ADR-0004](0004-topic-canonicalization.md): a user typing "maths" lands on
a survey topic while "linear algebra" lands on a deep one. Both are valid canonical topics
and the alias logic is unchanged; only the post-subscription *suggestions* differ.

### `target_cards` vs `min_cards`

The planner guesses before any generation happens and has no knowledge of quality-gate
rejection rates. If coverage were defined against `target_cards`, users would sit at 94%
indefinitely whenever quota is tight.

- `min_cards` — the coverage threshold. Completion is defined against this.
- `target_cards` — a ceiling and a priority weight. Cards beyond `min_cards` are enrichment.

### Generation is sequential within a subtopic, parallel across subtopics

Each generation call for a subtopic receives the titles of **all existing cards in that
subtopic, across all difficulties, tagged with their level**. Cross-difficulty inclusion is
deliberate: a beginner and an advanced card on the same subtopic must differ in depth, not
merely in wording.

Calls to the same subtopic are **sequential**, so newly generated titles are included in
the next prompt. Different subtopics have disjoint title lists and therefore run
**concurrently**. Sequential within, parallel across, with no throughput loss.

### Amendment to ADR-0006

- **Coalescing lock key** changes from `(topic_id, difficulty)` to `(subtopic_id)`. This
  is also what enforces the sequential requirement above.
- **Starvation signal** changes from "this topic's pool is low" to "**this subtopic is
  below `min_cards`**", which is far sharper and directly actionable.

### Completion and mastery

When a user has seen every card in every subtopic of a topic **at a given difficulty
tier**, that tier is complete.

Mastery is **per-user and per-tier**, not per-topic. Because of the difficulty mix in
`content-model.md`, a beginner exhausts beginner subtopics long before advanced ones. Per
tier is both the honest unit and the more useful one, because it chains directly into
promotion: *"You've mastered this at beginner level. Ready for intermediate?"* The
difficulty-progression UX is delivered by the same mechanism.

After completion the topic enters **revisit mode**: previously seen cards are re-served at
the user's chosen difficulty, with the completion state surfaced honestly rather than
disguised as new content.

### Dedup after this ADR

Prevention and detection are different jobs and we keep both:

- **Prevention** (curriculum + title list) optimizes **cost**. It is why quota goes further.
- **Detection** (content embedding) guarantees **correctness**. It is the only real guarantee.

A cheap preventive layer never earns the right to remove the check. The embedding
comparison is now **scoped to the subtopic** rather than the whole topic, making it both
cheaper and more precise.

**Intra-batch dedup is still required.** Neither the title list nor the
comparison-against-corpus catches a model writing three near-identical cards *within one
response of ten*. The batch must be compared against itself before insert. Assigning
distinct subtopics across a batch largely prevents this by construction.

## Consequences

**Easier**
- Coverage instead of mere non-overlap. The corpus teaches a subject rather than
  accumulating trivia about it.
- Gap detection is a `GROUP BY`, not an LLM judgment.
- Title lists stay small permanently, so the approach works identically at 50 cards and
  50,000.
- Completion, progress indicators, and difficulty promotion all fall out for free.

**Harder**
- **The curriculum pass is a high-stakes single point of failure.** Everything downstream
  inherits its quality. Mitigations: use the best available model for it, store the raw
  output for audit, and human-review the first several topics. It is one call per topic,
  so review is cheap while topic count is low.
- Curricula will need extension as subjects evolve. Subtopics are additive (cards hang off
  `subtopic_id`), but adding one un-completes a topic for users who had finished it. Treat
  this as a re-engagement hook ("new cards added"), not a bug.
- More schema and more moving parts than "generate cards about a topic".

## Alternatives considered

**Detection only** (generate freely, reject duplicates). Rejected: wastes the scarcest
resource, and produces no coverage guarantee.

**Title list without a curriculum.** The intermediate option. Better than nothing, but the
list grows unboundedly, the constraint is negative and weakly followed, and it still yields
no coverage guarantee.

**Curriculum per difficulty (three separate calls).** Rejected: a single call lets the
model design a coherent progression across tiers.

**Unbounded `target_cards`.** Rejected on both quota and, more importantly, because it
destroys completability.

**Bounding cards-per-subtopic only.** Rejected: it relocates unbounded growth into the
subtopic count rather than removing it. The budget must be on the total.

**Recursive subtopic nesting for large fields.** Rejected: see "Depth is fixed at two
levels" above. Splitting at the topic level is simpler and produces something users can
act on.

## Revisit when

- Curriculum quality proves to be the limiting factor on card quality, suggesting the
  curriculum pass deserves a stronger model or a multi-step refinement.
- Users complete topics much faster or slower than the 5-10 session target, indicating the
  5-25 band needs adjustment.
- Subtopic counts per topic grow large enough that curriculum generation itself hits output
  limits, in which case decompose by difficulty tier after all.
