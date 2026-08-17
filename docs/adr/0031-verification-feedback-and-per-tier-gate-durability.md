# ADR-0031: Verification rejection feedback, and a per-tier durable gate

- **Status:** Accepted
- **Date:** 2026-08-17
- **Deciders:** Anubhav
- **Amends:** [ADR-0030](0030-two-pass-quality-gate.md) — extends its "Duplicate-content
  feedback loop" section with a second feedback channel, and replaces `gate_and_persist`'s
  four global phase-barriers with a per-subtopic-tier pipeline.

## Context

Two gaps showed up running the pipeline against real Gemini keys across a full topic:

1. **Pass-2 verification rejections were dead ends.** ADR-0030 already closes the loop for
   near-duplicate rejections (`avoid_bodies` — full body text, no reasoning, since a
   similarity score is all dedup has). Verification rejections carry something dedup
   doesn't: a real `reason` string the judge model gave (e.g. "reads as intermediate, not
   advanced"). That reason was persisted to `rejected_card` and then never read again — the
   next run's writer had no way to know a subtopic-tier had failed verification before, let
   alone why.
2. **`gate_and_persist` was four global barriers over the whole batch** (correct everything,
   dedup everything, verify everything, persist everything, generate all questions) sharing
   one uncommitted session until the very end. A crash or quota exhaustion partway through a
   large multi-subtopic batch discarded every tier's already-spent LLM calls, not just the
   one in flight. Separately, a subtopic-tier that already had its cards but was interrupted
   before its questions were written (cards and questions commit as conceptually separate
   steps) had no path back — `existing_count` meeting `target_cards` makes
   `generate_subtopic_cards` skip drafting new cards for that tier on every future run,
   so nothing ever revisited it to backfill the missing questions.

## Decision

**Verification feedback loop.** `_load_subtopic_plans` fetches this exact subtopic-tier's
most recent `rejected_card` rows with `stage = VERIFICATION` (capped at
`settings.max_verification_feedback_bodies`, newest first, same recency-capped shape as
`avoid_duplicate_bodies`) as `(body, reason)` pairs, threaded into the next `generate_cards`
call as `rejection_feedback`. The prompt shows both, with the reason framed as the actual
problem to fix — distinct from `avoid_bodies`, which has no reasoning to show.

**Curriculum commits as soon as it's planned.** `resolve_and_plan_topic` commits right after
setting `topic.curriculum_generated_at`, instead of leaving it pending until
`gate_and_persist`'s fan-in. Card generation that follows does no DB access at all, so this
was free durability being left on the table.

**Missing-question backfill.** `_load_subtopic_plans` also fetches this subtopic's active
cards with no `Question` row (an outer join against `Question`). `generate_subtopic_cards`
threads these through unconditionally — including on the early-return path where a tier is
already at target and drafts nothing new — as `cards_missing_questions`.

**Per-tier gate, not global phases.** `_process_gate_item` runs one subtopic-tier's entire
trip through the gate — correction, dedup, verification, persist, question generation
(now over newly-accepted cards plus any backfilled `cards_missing_questions`) — start to
finish, independent of every sibling tier. Every tier runs via `asyncio.gather`. The LLM
phases touch no DB and run fully concurrently under the existing semaphore; dedup and
persist do touch `runtime.session`, which is not safe for concurrent use across coroutines,
so those sections serialize through a new `session_lock` instead of being pulled out into a
separate global phase. Each tier commits as soon as its own cards (and then its questions)
are written, not at one shared end-of-batch commit.

## Consequences

**Easier**

- A subtopic-tier that fails verification repeatedly now gets progressively better feedback
  instead of retrying blind — closes the same class of wasted-quota loop ADR-0030 already
  fixed for near-duplicates, for the other rejection stage that has real reasoning to offer.
- A crash, quota exhaustion, or process kill mid-batch now only loses the tiers still in
  flight. Previously-committed tiers (and the curriculum) stay committed regardless of what
  happens to the rest of the run.
- A subtopic stuck with cards but no questions (an interrupted prior run) self-heals on the
  next `generate_topics` invocation instead of staying broken forever.

**Harder**

- `gate_and_persist` now issues many small commits instead of one batch commit — more round
  trips to the DB, though each is small (one tier's cards, then that tier's questions).
- `session_lock` means dedup/persist across tiers is still effectively sequential relative to
  each other (only the LLM phases actually run concurrent within a tier's own pipeline) —
  this trades some theoretical DB-write parallelism for correctness, since `AsyncSession`
  can't be shared across concurrent coroutines at all.
- `rejection_feedback` and `avoid_bodies` are now both threaded into the same prompt; at
  high rejection volume for one subtopic-tier this grows the prompt by two feedback blocks
  instead of one — bounded by their respective `max_*_feedback_bodies` settings, same
  mitigation ADR-0030 already relies on for `avoid_bodies`.

**Committed to**

- Every subtopic-tier's gate outcome (cards persisted, questions persisted) is now visible
  and durable independently of every other tier in the same batch.
- A tier with cards but no questions is a recoverable, self-healing state, not a permanent
  gap requiring manual intervention.

## Alternatives considered

**Keep one global commit at the end of `gate_and_persist`, only add the curriculum
mid-commit.** Rejected: the whole point of the per-tier crash observed in practice was
losing already-gated cards from *earlier* tiers in the same batch, not just the curriculum.

**Backfill missing questions as a separate maintenance script/cron job instead of inline in
the normal generation path.** Rejected: `_load_subtopic_plans` already visits every
subtopic on every `generate_topics` call; a separate job would duplicate that traversal and
add another thing to remember to run, for a case (interrupted prior run) that's naturally
caught by the existing entry point.

**Fold `rejection_feedback` and `avoid_bodies` into one combined list instead of two
prompt-visible sections.** Rejected: they mean different things to the writer (near-dup says
"don't write this again"; verification feedback says "here's specifically what was wrong") —
collapsing them would lose the reason string's specificity inside undifferentiated body text.

## Revisit when

- Real second-pass data exists on whether `rejection_feedback` actually reduces the
  verification reject rate on a retry — this ships ADR-0030-shaped but untested against real
  content beyond unit tests of prompt threading.
- The per-tier commit granularity shows up as a real DB round-trip cost at scale (many
  subtopic-tiers, small batches) — at that point, consider batching commits across a few
  tiers rather than one-per-tier, trading back some crash-blast-radius for fewer round trips.
