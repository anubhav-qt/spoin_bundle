# ADR-0101: The curriculum declares a tier's grounding scope, and retrieval runs once per card within it

- **Status:** Accepted
- **Date:** 2026-09-06
- **Deciders:** project owner, implementing session
- **Supersedes:** [rag-design-space](../architecture/rag-design-space.md) §3.7 ("retrieve
  once per subtopic, not once per call")
- **Amends:** [ADR-0089](0089-retrieval-grounded-generation.md) (the open top-2 query),
  and partly delivers §3.10 and §3.11 of the design space

## Context

Astronomy is the first authored topic: 10 subtopics, 30 subtopic-tiers, 568 target
cards, against a corpus of 9 documents and **152 chunks**. Reading what the pipeline
would actually do with it exposed three separate problems that turn out to be one.

**Retrieval was per subtopic *group*, cached.** `Grounding.for_subtopic` keys on
`subtopic_group_id`, and all three tiers of a concept share the entry — so each
subtopic's ~57 cards would be written from the same **two chunks, ~3,300 characters**.
Across the whole run at most **20 of 152 chunks** would be retrieved: 87% of a corpus
somebody hand-wrote would never reach a card. With `card_duplicate_threshold = 0.9` and
dedup scoped per subtopic-tier, ~19 cards from two passages is also precisely the
condition that manufactures near-duplicates for the gate to reject.

**The query was identical across tiers.** The authored format carries one `description`
per subtopic and the projection copies it to all three tier rows, so
`build_query(topic, title, description)` produced the same string for beginner and
advanced. §3.11 ("a beginner card and an advanced card want different passages") was not
merely unimplemented; the inputs made it impossible.

**§3.7's premise had expired.** It justified the per-subtopic cache on "the query is
known before generation and **does not change within a subtopic** (asymmetry 2)". That
was true when it was written. [ADR-0059](0059-plan-before-writing.md) then added a
planning pass that produces a `CardPlan` — `canonical_title`, `content_direction` — for
every card *before* any card is written. A per-card query has existed ever since; §3.7
simply predates it.

Meanwhile two asymmetries in the same document pointed at the answer and had not been
taken up. **Asymmetry 1:** retrieval is offline and batched, there is no p99 to protect,
so "expensive retrieval is affordable". **Asymmetry 4:** *we own the authoring* — which
"moves work from retrieval time to authoring time, the cheapest possible place to put
it".

## Decision

**The curriculum declares, per tier, which corpus sections its cards may be written
from. Retrieval runs once per card, ranked within that scope.**

```yaml
tiers:
  beginner:
    target_cards: 16
    card_types: { prose: 5, ascii: 5, diagram: 3, comparison: 3 }
    grounding:
      - "astronomy/physics/astronomy/stellar-structure.md#Physical Foundations: Hydrostatic Equilibrium"
      - "astronomy/physics/astronomy/tips-and-tricks.md#Common Misconceptions: Stellar Optics"
```

### Why the author declares the scope and the machine ranks inside it

This is CLAUDE.md's rule — *the generator is trusted for taste, never for constraints* —
applied to retrieval, which was the last place in the write path still guessing.

- **The constraint is the author's.** Which passages teach this tier is knowledge they
  already hold; they wrote both the corpus and the curriculum. Embedding similarity was
  standing in for that knowledge and getting it wrong 87% of the time.
- **The taste is the machine's.** Which of a dozen candidate passages best fits *this*
  card is a ranking problem, and it does it better than a human would do it 568 times.

**Per-card authored grounding was rejected.** To name grounding per card the author must
know what the cards are, which means authoring a 568-row manifest — at which point it is
not a curriculum, and it contradicts
[authored-curriculum.md](../architecture/authored-curriculum.md)'s premise that the
model's remaining job is writing cards for a subtopic somebody already decided should
exist. The tier is the finest granularity a human can declare without writing the cards.

### The scope is a preference, not a wall

When a card's declared scope cannot supply `k` chunks, the shortfall is topped up from
an open corpus-wide query. The declared sections still rank first; the allowance only
fills what is left.

**The trigger is structural — fewer chunks came back than were asked for — not a
similarity floor.** No calibrated floor exists, and inventing a constant to defend a
guess is worse than not having one. Every card records the chunks it was grounded on, so
the first real run can settle what a floor should be, if one is wanted at all.

**It is counted, never silent.** `grounding_allowance_used` is reported per tier,
separately from every failure count. A tier that keeps using the allowance is reporting
that its declaration is too narrow — feedback for the author, not an error. This is the
same rule as everywhere else in the pipeline: a *fallback* and a *failure* are different
facts and never one number.

### One block per call, exact citations per card

Retrieval is per card; the prompt carries the **deduplicated union** for the batch, not a
block per card addressed to individual cards. Addressing passages in the prompt — "card 1
write from P1,P2; card 2 from P3,P4" — would load the scheme onto instruction-following,
which [ADR-0090](0090-hybrid-gemini-mistral-generation.md) names as the drafting model's
weak spot. The union costs less than the arithmetic suggests and is self-limiting: cards
in one batch share a subtopic, so their passages overlap and collapse; a batch that
genuinely spreads earns the breadth it takes.

`card.grounded_chunk_ids` stays exact regardless, because we know which query returned
what. It is now written **at draft time**, so it means "the passages retrieved for this
card" rather than "the passages this card's subtopic got" — which is what ADR-0089
wanted and what §3.12's retraction pipeline needs. A rejected draft keeps its citation
too, so a bad passage is traceable to everything it produced.

### The gate follows the card

ADR-0089's invariant — the writer, the corrector and the verifier see the *same*
sources, so a disagreement between them is about the writing rather than about which
evidence each happened to hold — is preserved by reading the drafts' recorded chunk ids
back and rendering *those*, instead of re-querying the subtopic. Without this, per-card
drafting would have quietly reintroduced the coin flip that ADR exists to remove.

### Addressability: `chunk.heading`

A `<path>#<heading>` reference resolves by joining `(document.source_path,
chunk.heading)`. `heading` became a real column for this: matching the front of
`chunk.text` would resolve `#Ownership` to `## Ownership Foundations`, silently grounding
a tier on the wrong passage, and would break the day the contextual-header format
changed.

`make curriculum-check` validates every reference against
`frog.ingest.contract.parse_document` — **the same parser the ingester chunks with** — so
a reference that validates is a reference that will resolve to a row. It names the near
miss when a heading does not match, because these are long strings copied by hand.

### Batching is packed, not counted

A drafting round is packed to fit two budgets with the overflow becoming the next round,
using `pack_by_tokens` — the spillover machinery [ADR-0085](0085-token-window-metering.md)
already applies to both gate passes. Two budgets, because for a drafting call the binding
constraint is usually **output**: the response carries N whole card bodies, and one
truncated at the model's cap fails to parse, losing *every card in the batch* rather than
the overflow.

## Consequences

**Easier.** A curated corpus is actually used rather than sampled. A beginner tier and an
advanced tier draw on different material, as authored. Near-duplicate pressure drops,
because cards stop being written from the same two passages. Provenance becomes real:
"which cards did this chunk ground?" is answerable per card.

**Harder.** Authoring cost rises — 30 tier-level declarations for astronomy rather than
10 source lists. Renaming a `##` heading breaks every curriculum naming it, though
loudly, at `curriculum-check`. Retrieval work rises from one query per subtopic to one
per card; it is affordable (asymmetry 1, local unmetered embedder) but it is no longer
free.

**Given up.** Cross-topic serendipity, mostly. [ADR-0088](0088-the-spoin-universe.md)
made retrieval cross-topic by default because an unexpected supporting passage is a
feature. Inside a declared scope it cannot happen; the allowance is the only route back
in. Accepted for a corpus this curated, and the allowance counter is what will show
whether it was the wrong call.

## Alternatives considered

**Raise `grounding_chunks` from 2 to 6.** One line, no code. Rejected as the answer
though kept as a knob: it does not fix the identical-across-tiers query, does not make
citations per card, and still reaches only one query's worth of corpus per subtopic —
deeper, not wider.

**Per-card blocks addressed in the prompt.** Sharpest, and rejected on the token
arithmetic and on ADR-0090's warning: 14 cards x 2 chunks x ~1.7k chars is ~12k tokens of
grounding before canon, avoid-bodies and plans, and the addressing is exactly the kind of
instruction the drafting model is weakest at.

**A similarity boost instead of a filter.** Rejected: the boost constant would be
indefensible, and it makes every retrieval partly open, which contradicts the
"declared scope is authoritative, allowance is rare" shape the owner chose.

**Keep `sources` at the subtopic and add `grounding` at the tier.** Rejected — two fields
naming corpus material is a drift surface, and the subtopic-level one had no consumer.
`sources` is deleted; `curriculum_subtopic.source_paths` is derived from the tiers.

## Revisit when

- **The allowance counter runs high.** Either declarations are too narrow (authoring
  feedback) or the scope model is wrong for a topic shape we have not met yet.
- **A run shows the scope hurting.** If scoped grounding does not beat the open query on
  accept rate, §10 of authored-curriculum.md's open question resolves the other way and
  this becomes a preference rather than a filter.
- **Per-claim verification (§3.10) is built.** The verifier currently reads back the
  drafter's passages. Retrieving per claim would be sharper and this ADR is what makes
  the plumbing for it exist.
- **A floor for the allowance is wanted.** Set it from measured score distributions, not
  from taste.
