# ADR-0057: A per-tier redraft loop closes the gate-rejection gap left by a single draft-and-gate pass

- **Status:** Accepted (amends [ADR-0026](0026-one-shot-pipeline-redesign.md), addresses [task 0023](../tasks/0023-generation-completed-status-hides-gate-attrition.md))
- **Date:** 2026-08-24
- **Deciders:** Anubhav

## Context

`generate_subtopic_cards` drafted a subtopic-tier to its full `target_cards` exactly once,
ran the two-pass quality gate (ADR-0030) exactly once, and returned. The gate rejects some
fraction of every batch — structural failures, near-duplicates, pass-2 verification — with
no loop-back to draft replacements for whatever it rejected. A run that "completed" without
error routinely landed well under `target_cards` anyway: confirmed live on a real topic at
613/743 cards (82%).

Task 0023 covers the user-facing half of this gap (the "Ready" badge claiming completion it
hadn't earned) and was already fixed client-side. This ADR is the other half: the pipeline
itself never tried again.

## Decision

**A per-tier redraft loop (`_redraft_until_bar` in `pipeline/nodes.py`), run after the first
draft-and-gate round, that keeps drafting and gating in rounds until each tier clears a
completion bar or is judged unable to.**

The bar differs by whether this run is the tier's first pass:

- **First-ever pass** (`existing_count == 0` when this run started): chases
  `Settings.first_pass_completion_fraction` (90% by default), not literal 100%. Some
  shortfall on a first pass is the gate doing its job, not a bug — the tier doesn't have to
  clear the last few percent itself.
- **A later pass** (a `scan_and_generate` backfill or any re-invocation on an
  already-started tier): chases the full 100%. This run IS "the next time a worker picks it
  back up" that task 0023 promises, so it must not hand off early again.

**No round cap.** Accepted cards only ever go up round over round — more rounds strictly
cannot make a tier worse — so there is no reason to stop a tier that is still making
progress. Instead there are two independent per-tier stop conditions, each triggered by
`_STUCK_ROUND_THRESHOLD` (5) consecutive unproductive rounds:

- **`stuck_rounds`** — the gate accepted zero of the tier's drafts. A real, repeated
  rejection (e.g. task 0011's missing difficulty-example catalog), not an unlucky round or
  two. Logged as REJECTED.
- **`no_verdict_rounds`** — the generator call itself returned zero items: quota exhaustion,
  a malformed batch response, the ADR-0056 client-side timeout. The gate never saw this
  content, so it is not evidence the content is bad. Logged as FAILED, and kept as a
  separate counter from `stuck_rounds` — conflating the two would misread a quota-exhausted
  run's give-up log as a content-quality problem (this repo's "failed vs rejected are never
  the same number" rule).

`_ABSOLUTE_MAX_REDRAFT_ROUNDS` (200) is a pure defensive backstop against a bug in either
guard, not a real operating limit — hitting it logs a warning naming it as such, since
reaching it means the guards themselves are broken, not that a subtopic is legitimately
taking this long.

Each redraft round re-queries the tier's own just-persisted `RejectedCard` rows
(`_recent_rejection_context` in `persistence.py`) so the feedback shown to the writer is
genuinely from earlier in the SAME run — those rows didn't exist when the run's initial
`_load_subtopic_plans` query ran. The feedback surfaces both `STRUCTURAL` and
`VERIFICATION` stage rejections (not only `VERIFICATION` — see "Also fixed" below), the
full rejected body plus the reviewer's exact reason, not just a reason string
(`_format_rejection_feedback` in `langchain_impl.py`). Existing question stems are
re-queried the same way each round (`_current_question_stems`), so a redraft round's own
question generation doesn't repeat an angle a prior round in this same run already wrote.

## Also fixed: a real overshoot bug found while testing this

The original per-tier draft loop bounded itself by the tier's ABSOLUTE `target_cards`,
never subtracting `existing_count` — so any re-invocation of `run_generation_pipeline` on an
already-started topic drafted a WHOLE EXTRA `target_cards`-sized batch on top of what was
already active. Confirmed live: three subtopics on a real topic landed at roughly double
their `target_cards` from one manual backfill run. This is a pre-existing bug, unrelated to
the redraft loop itself, but it directly breaks the exact "a worker picks the topic back up
later" scenario this ADR is about, so it had to be fixed for the redraft loop to mean
anything. Fixed by bounding the draft loop (and its per-card-type quota split) by the real
deficit (`target - existing_count`) instead of the absolute target.

## Consequences

- A topic's card count converges toward its declared `target_cards` instead of silently
  settling wherever the gate's single-pass rejection rate happens to leave it.
- Generation calls per topic go up — a topic whose content keeps clearing the gate on the
  first try costs the same as before, but a topic near the missing-difficulty-catalog
  failure mode (task 0011) now spends up to 5 extra rounds finding that out, instead of 0.
  There is no budget cap on this beyond the stuck guards themselves.
- The frontend must not claim unconditional completion — `GenerationProgressPanel.tsx`
  distinguishes "Ready" from "Ready · filling in" using the same per-subtopic
  `cards_done`/`cards_target` data the redraft loop is closing the gap on (task 0023,
  direction 1, already shipped).
- `scan_and_generate.py`'s backfill runs still bypass the `GenerationJob` table (task 0023,
  direction 2, still open) — that gap is independent of this ADR and is not closed by it.

## Alternatives considered

- **A fixed round cap on first-pass tiers** (`max_redraft_rounds`) was implemented first and
  removed before landing. Rejected because accepted cards only ever increase round over
  round — a cap trades away real completion for a number with no principled value, when the
  stuck guard already detects "this cannot pass" directly instead of guessing at a round
  count that might cut off a tier that was about to succeed.
- **A stuck threshold of 2** (instead of 5) was the first version. Rejected: two consecutive
  misses is well within normal variance (a small batch, a borderline dedup call) and is not
  evidence anything is actually stuck — the threshold needs enough consecutive misses to
  distinguish "genuinely rejecting" from "had a rough round."
- **One shared stuck counter for both a gate rejection and a generator call failure** was
  the first version of the guard. Rejected on code review: it produces a give-up log that
  asserts "the gate is rejecting this content" even when the real cause was the call never
  returning a verdict at all — exactly the failure/rejection conflation this repo's own
  rule warns against.

## Revisit when

- The redraft loop's total call volume becomes a real quota cost at scale — worth budgeting
  per-topic rather than leaving both stuck guards as the only ceiling.
- Task 0023's direction 2 (reconciling `scan_and_generate`'s backfill with `GenerationJob`)
  lands — at that point, re-check whether a topic's "Ready · filling in" state is actually
  getting resolved by later scanner runs, or just sitting there.
