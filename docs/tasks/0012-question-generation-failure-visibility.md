# Task 0012: Diagnose silent question-generation failures for specific subtopics

**Owner:** unassigned

## The problem

A live run against real Gemini keys (2026-08-17, `dsa` topic) closed most of the
card/question gap — 44 subtopics went from 22 with a mismatch down to 13, and those 13 are
off by only 1-3 (consistent with [`QuestionDraft`'s new structural
validator](../../apps/api/src/spoin/generation/base.py) correctly catching a handful of
malformed items instead of crashing).

Two subtopics did not improve at all:

- **Graph Foundations, Traversals & Connectivity [advanced]** — 11 cards, 0 questions
- **Bit Manipulation & Elementary Number Theory [intermediate]** — 15 cards, 1 question

These aren't a card-count shortfall (`_load_subtopic_plans`'s `cards_missing_questions`
backfill, see [ADR-0031](../adr/0031-verification-feedback-and-per-tier-gate-durability.md),
already re-targets them every run) — question generation itself keeps failing for these
specific subtopics, run after run.

## Why it matters

The backfill fix means a plain rerun of `generate_topics` silently retries these same
subtopics and (per the observed pattern) silently fails the same way again, burning quota
for zero progress. Worse: **there's currently no logged reason why.**
`_process_gate_item` (pipeline.py) only counts `questions_rejected` from
`_generate_questions_for_group`'s `failures` list — it never logs the actual failure
strings, so even after a run finishes there's no way to tell, from the log alone, whether
this is:

- The generator call itself erroring out (network, quota exhaustion at that moment,
  malformed response for the whole batch)
- Every individual item failing `QuestionDraft`'s validation (all garbled MCQ options, e.g.)
- Something else entirely

## What to do

1. **Add logging first, before trying to fix anything.** In `_process_gate_item`
   (pipeline.py), log `question_failures` (the actual strings, not just the count) at
   `logger.info` or `logger.warning` per subtopic-tier, same as `gate: near-dup REJECTED`
   already does for card rejections. This alone should answer whether it's a whole-call
   failure or per-item validation failures.
2. Rerun `generate_topics "dsa"` (or a smaller repro — the affected subtopic IDs are in this
   task's git blame / the run's persisted `topic_id`/`subtopic_id`) and read what the new
   logging says for these two subtopics specifically.
3. Fix whatever the logging reveals. If it's per-item validation failures, the actual model
   output causing them (e.g. `wire-result.cards` shape mismatches) should be visible in the
   error strings once step 1 lands. If it's a whole-call failure, check whether it correlates
   with quota exhaustion timing (cross-reference the `quota: acquired` log lines around the
   same timestamp).

## Hand back

- The two named subtopics (or whichever are still failing at the time this is picked up)
  generating questions successfully on a rerun.
- The actual root cause, written down here or as a follow-up ADR if it reveals something
  structural (e.g. a prompt that reliably breaks on certain content) rather than a one-off.

## Timebox

Not started. Step 1 (logging) is small, under an hour. Steps 2-3 depend entirely on what the
logging reveals — could be a five-minute fix or a real prompt/schema problem.
