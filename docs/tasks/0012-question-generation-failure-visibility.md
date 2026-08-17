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

## Update 2026-08-17: found and fixed a related bug (wrong-card questions), technique noted

While doing a content-quality read pass, a *different* bug was found and fixed in the same
session: `generate_questions` was cross-wiring questions to the wrong card because
`card_index` was a self-reported model field with no instruction telling the model what it
meant or that it had to match (see the commit fixing `langchain_impl.py`'s `_QUESTIONS_SYSTEM`
and `_WireQuestion.card_index`). This is a plausible *contributing* cause for subtopics that
"fail to produce enough questions" too — if `_generate_questions_for_group`'s bounds check
(`0 <= draft.card_index < len(chunk)`) rejects a mislabeled item as out-of-range, that's a
silent per-item loss that would show up as exactly this task's symptom (cards with fewer
questions than expected) without necessarily being a whole-call failure. Worth checking
whether the two named subtopics' failures correlate with this once the logging from step 1
lands — they might turn out to be the same root cause wearing a different symptom.

### Detecting existing wrong-card questions: an embedding-similarity technique

Both `Card.content_embedding` (body) and `Question.embedding` (stem) already exist in the
DB, so a mismatch can be screened for cheaply via pgvector cosine similarity, without an LLM
call per pair:

```sql
SELECT q.id, 1 - (q.embedding <=> c.content_embedding) AS sim
FROM question q JOIN card c ON c.id = q.card_id
WHERE q.status='active' AND c.status='active'
ORDER BY sim ASC;
```

**Distribution observed on the `dsa` topic (813 active questions, post this session's live
run):** `sim < 0.50`: 4, `< 0.60`: 12, `< 0.65`: 27, `< 0.70`: 52, `< 0.72`: 61.

**This threshold alone is not a safe cutoff for automated deletion** — an LLM verification
pass (ask a cheap model "does this question test content actually in this card's body,
yes/no, for each pair" batched ~8 at a time) on the 61 candidates under 0.72 found both false
positives (10 of 61 were genuinely correct pairs the embedding score simply undervalued —
e.g. "Building a Huffman Tree" paired with a question about its greedy step, or "Egg Drop
State Inversion DP" correctly paired despite phrasing drift) and confirmed 51 real
mismatches. A pure body-vs-stem embedding comparison conflates "different phrasing of the
same idea" with "different idea entirely" — it's a decent triage filter to shrink an LLM
verification pass from 813 pairs to ~60, not a standalone detector.

The 51 confirmed mismatches were deleted from `question` (cascades are clean —
`UserQuestionSeen`/`QuizAttemptQuestion` FKs are `ondelete=CASCADE`, and no real user answers
existed yet for this freshly-generated content) so they'd get picked up by
`cards_missing_questions` backfill and regenerated with the `card_index` fix in place.
**If this technique gets reused for real (not just a one-off cleanup), it belongs as a
proper script/task, not copy-pasted ad hoc again** — the 0.72 threshold and batch-of-8 LLM
check shape are what worked for `dsa`'s specific content mix; recalibrate before trusting it
on a different topic's embedding distribution.
