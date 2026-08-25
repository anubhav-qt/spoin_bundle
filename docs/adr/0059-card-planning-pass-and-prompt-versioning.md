# ADR-0059: A planning pass before card writing, and a prompt version stamped on everything it produces

- **Status:** Accepted (amends 0026, 0030, 0057)
- **Date:** 2026-08-25
- **Deciders:** Anubhav

## Context

Until now, one `generate_cards` call did three different jobs at once:

1. decide which distinct ideas within a subtopic-tier deserve a card,
2. decide what form each of those should take (prose, code, diagram, comparison, ascii),
3. actually write all of them well.

A prompt that has to cover all three can only be generic about each. The card-type
system prompts (`CARDS_CODE_SYSTEM` and friends) are the closest thing to focus we
had, and they are one paragraph bolted onto a shared header that is mostly about
what NOT to repeat.

Two consequences of that shape showed up in the live runs
([run 2](../architecture/generation-pipeline-run-2-benchmark.md),
[run 3](../architecture/generation-pipeline-run-3-benchmark.md),
[run 4](../architecture/generation-pipeline-run-4-benchmark.md)):

- **Near-duplicate rejections are structural, not accidental.** No writer call has
  ever seen the whole tier. Each one gets `existing_titles` — the cards that
  happened to land *before* it — and is asked to be different from them. Two calls
  writing concurrently, or one call writing five cards in a batch, have no way to
  separate ideas they cannot both see. The dedup gate then catches the overlap and
  throws a card away *after* it was written, which is the most expensive possible
  place to notice.
- **The card-type decision was being made by round-robin in Python**
  (`generate_subtopic_cards` picks whichever type has the largest unmet quota), not
  by anything that had read the material. That is fine as budget accounting and
  wrong as a content decision: it will happily demand a code card for a subtopic
  where no code exists to show.

Separately, we have no way to tell content produced by one generation of prompts
from another. `Card.version` looks like it would help, and does not: it is
family-scoped regeneration lineage (`UniqueConstraint("family_id", "version")` —
v2 of a card *replaces* v1 of that same card), a completely different axis. So
every quality judgement so far has been made over a corpus that silently pools
everything the pipeline has ever written.

## Decision

**Add a planning pass — a "pre-processing gate" — before any card is written, and
stamp `gen_meta.prompt_version` on everything the pipeline persists.**

`ContentGenerator.plan_cards` runs once per subtopic-tier, on the **generator**
ladder (ADR-0028), and returns one `CardPlan` per card the tier intends to write:
a `canonical_title` (the concept), a `card_type` (the form), an `asset_direction`
(what the diagram/code/art should actually show), and a `content_direction` (the
angle, and what separates this card from its siblings). The writer calls that
follow are each handed their slice of those briefs and asked to write exactly
those cards.

Three things make this worth a call rather than a longer prompt:

- **The planner is the only call in the pipeline that sees a whole tier at once.**
  It is therefore the only one positioned to make the cards differ deliberately,
  which is the actual fix for near-duplicate attrition — separating ideas before
  they are written rather than detecting the collision afterwards.
- **Each prompt now describes one job.** `PLAN_SYSTEM` says nothing about how to
  write prose, because the call using it never writes any; the writer prompts no
  longer have to carry the burden of inventing coverage. This is the hypothesis
  being tested — see "Revisit when".
- **The form decision moves to something that has read the material.** The
  round-robin becomes what it should have been all along: a budget passed to the
  planner as guidance, with the realised mix still counted in code afterwards.

**The planner is trusted for taste, never for constraints** (CLAUDE.md), and this
is where that rule does real work. `card_type` is a *request*: `_card_matches_type`
still counts the realised mix against the tier's quota exactly as before, because
the planner asking for four diagrams does not make four diagrams exist. Likewise
`type_quotas` goes to the planner as "roughly this shape", not as a rule — a tier
padded to hit a quota is the failure mode that budget was meant to prevent.

**Planning failure is survivable by design.** An empty or failed plan means the
writer calls run unplanned — precisely the pre-ADR-0059 path — and the tier still
produces cards. A planning call that never returns must cost us an improvement,
never a card. The single exception is `QuotaExhaustedError`, which propagates like
every other call's does: that is a run-level stop signal, not a per-call failure.

`_redraft_until_bar` (ADR-0057) plans too, not just the first pass. A tier that
lands short is exactly the one whose remaining cards are hardest to place, and the
redraft planner is the only call that sees the tier's fresh rejection context
*before* deciding what to attempt next.

**`gen_meta.prompt_version = 2`** is stamped on every card, question, and rejected
draft this pipeline writes. Rejections are stamped deliberately: a v2-vs-v1
comparison that only sees what survived the gate measures the gate, not the
prompts. Corpus written before this carries no `prompt_version` key at all and is
**v1 by absence** — nothing backfills it, because rewriting `gen_meta` across the
live corpus would be a bulk `UPDATE` on real production content to record
something its absence already says. Query v1 as
`gen_meta->>'prompt_version' IS NULL`.

## Consequences

**Easier.** Every prompt is now narrow enough to be worth iterating on
independently — which is the point: the next step
([task 0026](../tasks/0026-few-shot-examples-from-manual-review.md)) is to add
worked good/bad examples to each of them once v2 cards have been reviewed by hand
on the frontend, and that is only tractable when each prompt has one job to
exemplify. Near-duplicate rejection should fall, since overlap is now prevented at
plan time rather than detected post-writing. And for the first time, "did that
change help?" is an answerable question rather than a vibe, because the two
corpora are distinguishable in SQL.

**Harder / costlier.** One extra generator-pool call per subtopic-tier per pass
(including each redraft round). At 500 RPD per model on the generator ladder
versus 20 on the thinking ladder, this is the cheap pool and the cost is real but
small — the thinking pool, which is the actual bottleneck, is untouched. More
seriously: **there is now a second place a card's content can go wrong.** A bad
plan yields a bad card that the writer had no license to fix, and the gate will
reject it for a problem that was introduced one stage earlier than the gate can
see. The `plans` log line and `RejectedCard` rows are what make that traceable;
if it turns out to be common, the planner is the thing to fix, not the writer.

**Committed to.** Keeping both the planned and unplanned writer paths working —
the fallback is not decoration, it is what stops a planning outage from becoming a
generation outage. And to bumping `CARD_PROMPT_VERSION` whenever prompts change
enough that content either side shouldn't be pooled when judging quality, which is
the only thing that makes the stamp worth having.

## Alternatives considered

**Put the planning instructions into the existing `generate_cards` prompt (no
extra call).** Free, and it was the first instinct. It loses the one property that
motivates this: a single call still cannot see a whole tier at once, because the
tier is written across several batched calls and often several rounds. It would
also make the prompt longer and *less* focused, which is the opposite of the
hypothesis under test.

**Run the planner on the thinking ladder.** Planning feels like the "judgment"
half of the ADR-0008/0028 split. But the split is about *consequence*, not
prestige: a bad gate verdict silently admits wrong content, while a bad plan
produces a card that the gate still independently judges. Planning is upstream of
the gate, not a replacement for it. Spending 20-RPD-per-model thinking quota on it
would tighten the pipeline's real bottleneck to buy nothing the 500-RPD pool
can't.

**Let the planner produce the card bodies too (collapse plan and write).** Then
the writer is a formatter and the whole focus argument collapses — one call is
back to doing every job at once, just with more structure in its output. `CardPlan`
deliberately has no `body` or `summary` for this reason.

**Plan only the first pass, leave redrafts unplanned.** Cheaper, and it was
tempting. It would have made a v2 tier a *mixture* of planned and unplanned cards,
which muddies exactly the comparison `prompt_version` was added to make possible.

**Use `Card.version` for v1/v2 instead of `gen_meta`.** It is already there and
already an integer. It also already means something else entirely (regeneration
lineage within a family), and overloading it would break the partial unique index
on `(family_id) WHERE status = 'active'` the ranking signal depends on.

**Backfill `prompt_version: 1` across the existing corpus.** Tidier to query. It
is a bulk `UPDATE` on real production content (CLAUDE.md's database rule) to write
down a fact that the missing key already conveys.

## Revisit when

- **The hypothesis fails its own test.** v2 content is reviewed by hand on the
  frontend against v1 (task 0026) and is not better — near-duplicate and
  verification rejection rates unchanged or worse, hand review no more favourable.
  Then focused prompts were the wrong theory, and the extra call and the extra
  failure surface are not being paid for. Revert to unplanned generation; the
  fallback path means that is a call-site change, not a rewrite.
- **Plan-stage errors show up in the rejection data.** If `RejectedCard` rows
  start clustering on "the concept itself was wrong for this subtopic" rather than
  on prose quality, the planner is the regression, and it needs the calibration
  (or the stronger ladder) that this ADR declined to give it.
- **Generator-pool RPD becomes the binding constraint.** The whole cost argument
  here rests on the generator ladder having ~25x the daily headroom of the
  thinking ladder. If that stops being true, the per-tier planning call is the
  first thing to make conditional.
