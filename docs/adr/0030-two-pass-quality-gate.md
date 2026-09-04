# ADR-0030: Two-pass, self-correcting quality gate

- **Status:** Accepted
- **Date:** 2026-08-17
- **Amended by:** [ADR-0090](0090-hybrid-gemini-mistral-generation.md) — this ADR's two
  passes no longer run on the same model ladder. `verify_cards` returns a verdict and
  stays on the thinking cells permanently; `correct_cards` rewrites prose against
  retrieved source ([ADR-0089](0089-retrieval-grounded-generation.md)) and moved to the
  generator ladder, from the first pass onward. The gate is still two passes; they are
  no longer the same kind of work.
- **Deciders:** Anubhav
- **Extended by:** [ADR-0031](0031-verification-feedback-and-per-tier-gate-durability.md) --
  adds a second feedback channel (verification rejection reasons, alongside this ADR's
  near-duplicate `avoid_bodies`) and replaces `gate_and_persist`'s four global phase-barriers
  with a per-subtopic-tier pipeline.
- **Supersedes:** [content-model.md](../architecture/content-model.md)'s original "Quality
  gate" section -- checks 2-4 (topic conformance, difficulty, factual accuracy) as
  independent reject-only checks are replaced by the two-pass design below. Check 1
  (near-duplicate detection) is unchanged.
- **Amends:** [ADR-0028](0028-key-model-quota-ladder.md) / [ADR-0008](0008-local-gpu-generation.md) --
  the thinking-pool call originally specified as `judge_difficulty` (rate-and-reject, single
  pass) is replaced by two thinking-pool calls, `correct_cards` and `verify_cards`. Still the
  same pool, same "always the strongest available model" rule -- only the shape of the call
  changes.

## Context

The design content-model.md originally specified was **detect-and-reject**: an independent
LLM judge rates each card's difficulty and factual soundness in one pass, without seeing the
requested difficulty, and any disagreement fails the card. Combined with a separate,
embedding-based topic-conformance check, a card had four ways to be thrown away entire:
near-duplicate, topic drift, difficulty mismatch, factual error.

That design throws away the whole card -- and the quota already spent generating it -- for
problems that are often small and mechanically fixable: a card that's 90% on-topic but
drifted in its last paragraph, or gets one date wrong, doesn't need to be regenerated from
scratch. It needs one paragraph rewritten. Under ADR-0003's free-tier-first constraint, quota
is the scarcest resource in the system; discarding an otherwise-good card is strictly more
expensive than fixing it, when the fix costs the same one LLM call either way.

The alternative raised in review: trust the judge model to *fix* what it can, and only reject
what it genuinely can't. This ADR adopts that.

## Decision

**The gate becomes two passes over the same batch, both against the thinking pool -- never
the generator pool, regardless of which pool actually wrote the card (ADR-0008's rule:
judgment always gets the strongest available model).** Pass 1 (`correct_cards`) batches
`judge_batch_size` (20) -- it rewrites whole bodies, so its output scales with the chunk
and a big one risks the output-token cap. Pass 2 (`verify_cards`) batches
`verification_batch_size` (40) -- a verdict is a few tokens per card, so the larger chunk
is safe and halves the thinking-pool calls this pass costs per tier (the scarce rung).

### Pass 1 -- correction

The model is shown each draft's full content (`title`, `canonical_title`, `summary`, `body`)
and the **canonical topic** it must belong to (`topic.canonical_name` + `topic.description`)
-- never the loose topic phrasing that might appear inside the card's own text.
**Difficulty is withheld.**

The model may rewrite `title`/`canonical_title`/`summary`/`body` in place to make the card
actually earn its topic assignment and to fix any factual error it finds -- it never changes
*which* topic or subtopic the card belongs to, only the content underneath that assignment.
This pass always returns a result for every input card; it never rejects. If nothing needed
fixing, the returned fields are the input, unchanged.

This replaces the standalone embedding-based topic-conformance check from content-model.md:
topic fit becomes something the model actively repairs, not something a cosine threshold
merely flags for disposal.

`content_embedding` is (re)computed from **pass 1's corrected `body`**, never the
pre-correction draft -- every downstream comparison (dedup, and eventually ranking) has to
read the text that actually shipped.

### Near-duplicate detection -- unchanged, runs here

Content-model.md's check 1 is untouched: local, free (`fastembed`/`HashEmbedder`, hard rule
5), subtopic-scoped against the existing corpus, plus an intra-batch comparison (the
same-batch problem ADR-0007 already named -- a model can write near-identical cards within
one response, and neither the corpus comparison nor the curriculum's title-list prevention
catches that).

**Intra-batch comparison is a running set.** Each new card (post pass-1 correction) is
compared only against cards already *accepted* earlier in the same batch, in order -- not an
all-pairs comparison. This mirrors how the corpus comparison already works (compare against
what exists so far) and keeps the cost linear in batch size.

A hit here -- corpus or intra-batch, above `card_duplicate_threshold` -- is a **hard reject**,
and happens **before** pass 2. There's no reason to spend a second LLM call verifying a card
that's about to be thrown out for being a duplicate of something else.

### Pass 2 -- verification

Survivors of dedup go back to the model, batched the same way, now **with their requested
difficulty visible**. The model:

- Confirms (or, if it disagrees, states) the difficulty the corrected content actually reads
  as.
- Gives a final `accepted: bool` -- catching anything pass 1's edit didn't actually resolve.

`accepted = false` here is a real, final rejection -- unlike pass 1, which never rejects.

### Rejections are persisted, not discarded

A card that fails structural validation, near-dup, or pass 2 verification is written to a new
`rejected_card` table (topic/subtopic, requested difficulty, the corrected title/body at time
of rejection, `stage` -- `structural` | `near_duplicate` | `verification` -- a `reason` string,
and `gen_meta`) instead of vanishing. It never becomes a `Card` row and is never counted
toward a subtopic's `existing_count`, so the next generation run (or a same-run top-up, if one
is ever added) sees the subtopic as still under target and fills the gap naturally.

The reasoning: content-model.md already treats a rejected card as informative (`gen_meta`
lets a bad *batch* be traced), and a per-card labeled example -- draft plus the specific reason
it failed -- is strictly more useful than a log line, for future work like evaluating gate
accuracy or fine-tuning the generator. Discarding it for free throws that away for nothing.

### Difficulty calibration examples

`difficulty` is a label; without a concrete anchor for what "beginner" versus "advanced"
actually *reads like*, both the writer (`generate_cards`) and the judge (`correct_cards`/
`verify_cards`) are calibrating against nothing but the word itself. Both now accept a
`difficulty_examples: dict[Difficulty, list[str]]` -- a few example card bodies per tier,
shown together so the *contrast* between tiers is visible, not just one tier in isolation.

**Source depends on whether the subtopic-tier is linked or standalone:**

- **Linked** (multiple tiers share a `subtopic_group_id` -- `SubtopicGroupPlan.tiers` has more
  than one entry): no separate examples are needed. `builds_on` (ADR-0026) already gives the
  higher tier the actual lower-tier cards for this exact concept, which is a more relevant,
  concept-specific calibration than a generic example could be. `difficulty_examples` is
  passed empty here.
- **Standalone** (`SubtopicGroupPlan.tiers` has exactly one entry -- the common case, since
  curricula are never forced to give a concept all three tiers): there is nothing in-subtopic
  to draw from, so a **hand-curated, topic-agnostic example catalog** fills the gap -- same
  "schema/plumbing now, content later" pattern as ADR-0021's ASCII scene catalog.
  `content/difficulty_examples.py` exists and is wired into every call site; the catalog
  itself is empty (returns `[]` per tier) until authored -- see
  [docs/tasks/0011](../tasks/0011-difficulty-example-catalog.md).

The judge's pass 1 (correction) receives the same three-tier example set regardless of which
specific difficulty a given card was requested at -- showing all three together doesn't leak
which one applies to *this* card, since every card in the batch sees the identical set. Pass 2
(verification) receives it too, now alongside the visible requested difficulty, for the same
calibration reason.

### Duplicate-content feedback loop

A near-duplicate rejection is wasted quota unless something changes before the same
subtopic-tier is asked to generate again. `_load_subtopic_plans` (pipeline.py) now also
fetches this exact subtopic-tier's most recent `rejected_card` rows with
`stage = near_duplicate` (capped at `settings.max_duplicate_feedback_bodies`, newest first)
and threads their **full body text** into the next `generate_cards` call as `avoid_bodies` --
distinct from `existing_titles` (titles of cards that were *accepted*): this is the actual
rejected content, shown as "do not write anything like this again," because duplication is a
body-similarity phenomenon a title alone can't convey.

Scoped to the exact subtopic (not the group) -- matching where the near-dup check itself is
scoped (`generation/dedup.py`'s corpus comparison), not the group-wide scope `existing_titles`
uses for cross-tier depth differentiation.

**This closes the loop only across separate pipeline runs, not within one run's retry
rounds.** `generate_subtopic_cards`' multi-round top-up loop (same node, same call) has no DB
access by design -- near-duplicate detection only happens later, once, in `gate_and_persist`,
so a rejection discovered there can't inform a round that already ran earlier in the same
`run_generation_pipeline` call. It DOES inform the next time generation runs for that
subtopic -- a later top-up pass, or a manual re-trigger -- which is the common case for an
under-target subtopic (ADR-0026's one-shot model means a shortfall gets revisited later, not
retried in a tight loop within the same call).

### Everything runs on every card

Same principle as content-model.md originally stated for the judge: batching makes this
affordable on the whole corpus, not a sample. Pass 1, dedup, and pass 2 all run on every
draft that survives the previous step -- no check in this gate is sampled.

## Consequences

**Easier**

- Fewer good cards thrown away for a fixable problem -- the common case (a mostly-right card
  with one wrong detail) now costs one LLM call to fix rather than one LLM call to discard
  plus another to regenerate.
- One coherent two-step "gate" replaces four independently-reasoned checks; topic conformance
  no longer needs its own embedding comparison and threshold to calibrate.
- Rejected drafts become a queryable, labeled dataset instead of a discarded batch -- useful
  later for evaluating the gate itself or the generator.

**Harder**

- **Doubles the thinking-pool cost of gating.** What was designed as one call per batch of 20
  (content-model.md's original judge) is now two -- pass 1 and pass 2 both hit the thinking
  pool's much smaller ladder (ADR-0028/0029), on top of curriculum, topic matching, and
  grading already sharing it.
- **Pass 1 can silently rewrite a card in ways nobody downstream sees.** There is no separate
  detector watching the corrector the way there was a standalone topic-conformance check --
  pass 2's spot-check (difficulty + final accept/reject) is the only backstop, and it isn't
  designed to catch "technically on-topic but now bland/generic" drift from over-correction.
- A card that fails pass 2 (e.g. a genuine difficulty disagreement) is discarded even though
  pass 1 already spent a rewrite on it -- `rejected_card` makes that sunk cost auditable, not
  avoided.
- `card_duplicate_threshold` remains uncalibrated (see content-model.md's open questions,
  and the note below) -- this ADR doesn't resolve that, it only fixes where in the pipeline
  the check runs.

**Committed to**

- Every draft that reaches the gate becomes exactly one of: an `active` `Card` row, or a
  `rejected_card` row. Nothing is silently dropped.
- `content_embedding` always reflects post-pass-1-correction body text.
- Both passes always run on the thinking pool, never the generator pool, regardless of which
  backend (cloud/local) wrote the original draft.

## Alternatives considered

**Keep the original four-independent-check, reject-only design.** Rejected per Context: wastes
the fixable-card case, which is the common case, not the exception.

**Fold near-duplicate detection into the LLM passes too** (tell the model "don't repeat
this list"). Rejected: this is exactly the weak negative-constraint problem ADR-0007 already
rejected for curriculum title lists -- LLMs are unreliable at avoiding a list, and cosine
similarity against the actual corpus is precise, free, and already built. Keep it as its own
step.

**Single verification-only pass, no correction pass** (i.e., actually wire up `judge_difficulty`
as originally speced, unchanged). Rejected in this conversation -- see Context: it's strictly
worse on quota for the common fixable-card case, for no accuracy benefit pass 2 alone
wouldn't already provide.

**Merge pass 1 and pass 2 into one call** (show difficulty from the start, ask for
correct-and-verify in one shot). Considered and rejected for now: asking a model to both edit
content AND independently critique whether that content matches a difficulty it was shown
risks the same self-report problem `DifficultyVerdict` was built to avoid in the first place --
seeing its own edit next to the answer makes "does this match?" too easy to rubber-stamp.
Keeping difficulty hidden until after the edit is committed is what makes pass 2 a genuine
independent check rather than the model grading its own homework in the same breath.

## Revisit when

- Real rejection/edit-rate data exists: if pass 1's edit rate is high enough that corrected
  cards start reading like a different voice than the generator's, the correction pass may
  need its own spot-check, not just pass 2's.
- The doubled thinking-pool cost (see Harder) becomes the actual bottleneck against ADR-0028's
  ladder -- at that point, consider skipping pass 1 for cards a cheap heuristic already thinks
  are fine, or merging the passes per the rejected alternative above once there's a cheaper way
  to avoid the self-grading risk.
- `card_duplicate_threshold` gets real calibration data from `fastembed` (task 0001-adjacent
  follow-up) -- see content-model.md's open questions; this ADR ships it at `0.9` as an explicit,
  more-conservative-than-0.93 placeholder pending that.
