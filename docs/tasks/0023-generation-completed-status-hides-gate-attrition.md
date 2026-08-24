# Task 0023: The frontend's "Ready" status doesn't reflect actual card completion, and nothing reconciles it once the idle scanner tops a topic back up

**Owner:** unassigned

## The problem

The "Explore Topics > Your Requests" panel's "Ready" pill is driven entirely by
`GenerationJob.status == "completed"`
(`apps/web/components/TopicDiscoveryModal.tsx:32-37`, sourced from
`TopicsService._latest_jobs` in `apps/api/src/spoin/topics/service.py:159-168`). That status
gets set the moment `run_generation_pipeline(...)` returns without raising
(`apps/worker/__main__.py:56-69`) -- it reflects "the pipeline ran without error," not
"every subtopic hit `target_cards`."

Within one run, the quality gate (dedup, structural checks, pass-2 verification, ADR-0030)
runs once, *after* the drafting loop finishes requesting cards -- there's no loop-back to
draft replacements for whatever the gate rejects. Landing at e.g. 97% of `target_cards`
instead of 100% is a completely normal single-run outcome, and the job is still marked
`"completed"` regardless.

Separately, `scan_and_generate.py`'s `find_incomplete_topics` (`status: "under_target"`,
`scan_and_generate.py:116-130`) does exist specifically to top up under-target topics, wired
into an idle-CPU cron daemon (`docs/architecture/automated-idle-generation.md`,
`scripts/idle_generation_runner.py`). But it re-invokes `run_generation_pipeline` directly,
bypassing the `GenerationJob` table entirely -- the same pattern `CLAUDE.md` already calls
out for `generate_topics.py`. So even when the scanner successfully fills in that last few
percent in the background, the frontend's "Ready" pill never changes: it's still reading a
`GenerationJob` row that said `"completed"` days ago and is never touched again. The signal
that resumes generation and the signal that renders "Ready" are two data sources that never
reconcile, in either direction.

## Why it matters

Confirmed live 2026-08-24: a real topic ("System Design & Distributed Systems") showed
"Ready" while sitting at ~97% card completion per its own progress dropdown. The user's own
read on this (correct, and the reason this is a task doc and not a bug report) is that
"Ready" showing before 100% is fine -- there's enough content for the topic to be usable.
What's actually missing is any doc or code path that makes that intentional: nothing states
that `"completed"` can mean less than 100% due to gate attrition, and nothing confirms
whether a specific "Ready" topic's remaining cards are still coming via the idle scanner or
will simply never be requested again. Per this repo's "failed vs rejected are never the same
number" rule and "a doc that's wrong is worse than no doc" rule, the gap is that today there
is genuinely no way to tell, from the frontend or from the `GenerationJob` row alone, which
of those two is true for any given "Ready" topic.

ADR-0053 already documents that `"completed"` and the separate live-coverage milestone
(`topic_live_coverage_fraction`, `topics/service.py:194-238`) are different clocks -- but
that's about the *feed-visibility* threshold, not this gap, which is about the *scanner
backfill* being invisible to the status the frontend actually renders.

## What to do

Two directions; the first is done, the second is still open.

1. **Make the desync visible instead of silent -- done, 2026-08-24.**
   `GenerationProgressPanel.tsx` already receives per-subtopic `cards_done`/`cards_target` and
   `questions_done`/`questions_target` from `GenerationProgressOut.subtopics` (it was already
   using them for the progress bar), so this ended up being purely client-side: no schema or
   `TopicsService` change needed. It computes `underTarget = status === "completed" &&
   subtopicsDone < totalSubtopics` and swaps the "Ready" badge for "Ready · filling in" (a
   distinct accent color, not the "done" green) and the "✓ Generation complete!" banner for an
   honest "✓ Ready to read — N/M cards so far. The rest may fill in later." Confirmed this was
   also worth noting: `stage: "done"` in the job's progress blob is written unconditionally at
   the end of every run (`_mark_progress_done` in `pipeline/nodes.py:1148`), same false signal
   as `status == "completed"` -- so the fix had to derive real completion from the per-subtopic
   counts, not from either `status` or `stage`.
2. **Make the scanner's backfill reconcile with `GenerationJob` -- still open.**
   `scan_and_generate.py`'s topped-up runs still bypass the `GenerationJob` table entirely (see
   "The problem" above) -- confirmed still true 2026-08-24. Have those runs write/update a
   `GenerationJob` row the same way the queue-driven path does, so a topic that gets backfilled
   later flips back to a fresh "Ready" (not "Ready · filling in") without the requester having
   to know a scan happened.

This still needs a decision recorded (a short ADR note, or at minimum an explicit statement in
`generation-pipeline.md` or ADR-0053) about what "Ready" is actually promising a user --
direction 1 makes the gap visible in the UI, but nothing documents the guarantee (or lack of
one) yet.

## Timebox

Small remaining -- direction 1 is done; direction 2 is one extra write plus the doc note.
