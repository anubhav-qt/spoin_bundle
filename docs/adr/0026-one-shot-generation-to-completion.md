# ADR-0026: One-shot generation to completion, no demand-driven refill

- **Status:** Accepted
- **Date:** 2026-08-17
- **Deciders:** Anubhav
- **Amends:** [ADR-0006](0006-demand-driven-pool-fill.md) (drops the fill-triggering
  mechanism this ADR built for generation; the feed-serving "degraded mode" question it
  also covers is explicitly NOT resolved here -- see "Open question" below),
  [ADR-0007](0007-curriculum-driven-generation.md) (drops the `subtopic_id` coalescing
  lock and per-subtopic starvation signal -- there is no more recurring fill to coalesce),
  [ADR-0024](0024-langgraph-for-card-generation-pipeline.md) (the graph gains a questions
  node and an ordering dependency between difficulty tiers; cross-topic concurrency and
  per-job failure isolation move to the worker, not the graph)
- **Fixed by:** [ADR-0041](0041-per-group-gate-and-persist.md) -- this ADR's own Decision
  section already says cards should persist as soon as their subtopic/tier's batch
  completes, but the actual graph wiring implemented a global fan-in barrier instead. ADR-
  0041 closes that gap; nothing else in this ADR changes.

## Context

ADR-0006/0007 designed generation as an ongoing process: a topic's subtopics have
`min_cards`/`target_cards`, a subtopic's pool can run low as users consume it, and running
low triggers a new `GenerationJob` to top it up -- coalesced per `subtopic_id` so 50
concurrent misses on the same starved slot don't spend a day of quota on one topic.

Revisiting that: a topic's curriculum already commits to a fixed card budget (~750
cards/topic, ADR-0007) and a quiz question bank sized so a user cycles through many
sessions before ever exhausting it (order 250-300 questions, exact number TBD) before
seeing a repeat -- and a repeat, once *everything* has been seen, is fine: it aids
retention rather than reading as staleness. That removes the reason a subtopic would ever
need topping up after its first pass. A topic's generation work has a natural end state:
curriculum planned, cards written to budget, questions written -- done, permanently, not
"until it needs refilling."

This also resolves what a `GenerationJob` actually represents. A topic only ever reaches
the pipeline in the first place because [ADR-0025](0025-batched-llm-topic-matching.md)'s
matching step decided it is genuinely new (not an alias onto something existing) -- so
"generate this topic" is inherently a one-time event per topic, never a recurring one.

## Decision

**A topic's generation is one pipeline run, start to finish: curriculum, then cards
(with difficulty tiers building on each other's actual content where linked), then
questions. Once that run completes, the topic is done -- no future job ever revisits it.**

```
topic arrives (post ADR-0025 matching: genuinely new)
  |
  v
curriculum call            unchanged from ADR-0007: one call, all tiers, subtopics
  |                         with target_cards, tiers linked via subtopic_group_id
  v
card generation, per subtopic, per difficulty tier
  - existing behavior unchanged: every batch sees every existing title (this
    subtopic, every difficulty) to prevent duplicates
  - NEW: for a subtopic_group's linked tiers, a higher tier's card generation
    additionally receives the ACTUAL CONTENT (not just titles) of that lower
    tier's cards, so advanced cards can genuinely build on what beginner/
    intermediate already covered rather than merely avoid repeating its titles
  |
  | cards persist and go live in the feed as soon as their subtopic/tier's
  | batch completes -- NOT held back until the whole topic (including
  | questions) finishes. Card serving and question generation proceed
  | concurrently, not sequentially, once cards for a tier exist.
  v
question generation, per subtopic, per difficulty
  - NEW: the pipeline's missing questions node (ContentGenerator.generate_questions
    already exists in the interface, unused until now) is wired into the graph
  - questions are generated FROM the cards just written for that
    subtopic/difficulty, same as content-model.md already specifies
  |
  v
topic marked done. No GenerationJob is ever created for this topic_id again.
```

### Difficulty count matters more than token count

Cost on the free tier is metered in **requests**, not tokens (ADR-0005). Passing a lower
tier's full card content into a higher tier's generation call costs nothing extra in
request count -- it's more data in the same call. The design lever here is exactly the one
ADR-0005 already established: batch more into each call rather than make more calls.

### Cross-topic parallelism and failure isolation move to the worker

Previously, `run_generation_pipeline` accepted a list of topics and the graph's own
internal `Send` fan-out ran them concurrently, sharing one DB session across the whole
call. That means one unhandled exception anywhere in the run aborts the entire batch --
acceptable when the pipeline's only caller was a manual CLI run, not acceptable once the
worker is claiming several unrelated topics' jobs per pass and a bug in one topic's
generation shouldn't take four others down with it.

**The worker now fires one `asyncio` task per claimed job, each with its own DB session,
gathered with per-task exception handling.** `run_generation_pipeline` itself is
unchanged and still accepts a topic list (the CLI can still hand it several topics at
once for convenience -- that path doesn't need isolation the way unattended worker runs
do); the worker just always calls it with a single-topic list, once per job, concurrently
across jobs.

This does not reduce what LangGraph is doing -- it clarifies the boundary ADR-0024 already
drew. LangGraph owns concurrency **within** one topic's run (subtopics and difficulty
tiers still fan out and merge inside the graph, now with a real sequencing constraint: a
linked higher tier can't start until its lower-tier sibling's cards exist). Concurrency
**across** topics/jobs is the worker's job, using plain `asyncio` -- no different in kind
from what ADR-0024's "Alternatives considered" already concluded about the worker/graph
split, just now stated for the multi-topic case specifically.

### `GenerationJob` simplifies

- `kind` (`curriculum` | `cards` | `questions`) stops meaning anything -- a job is just
  "run the one-shot pipeline for this topic," never a partial slice of it. The pipeline
  itself decides what a topic still needs (nothing does today, since a job only exists
  for a brand-new topic).
- The `subtopic_id` coalescing lock (ADR-0007's amendment to ADR-0006) is no longer
  needed -- there is no recurring per-subtopic refill to coalesce. The job's natural key
  becomes `topic_id`.
- `status`/`attempts`/`last_error`/`completed_at` are unchanged and still do real work:
  a topic's one-shot run can still fail partway (quota exhaustion, a malformed batch) and
  needs retry bookkeeping -- "one-shot" describes the *target* outcome, not a guarantee
  every attempt succeeds on the first try.

Schema migration (dropping `kind`, changing the coalescing index) is implementation work
for whoever picks up the updated task 0008 -- not decided further here beyond "the fields
described above stop being load-bearing."

## Open question: what happens to ADR-0006's feed-serving behavior?

ADR-0006 bundled two things together: (1) triggering a generation fill when a slot runs
low, and (2) how the **feed** serves a starved slot in the meantime (shorter pages,
degraded mode, hysteresis, "more coming soon" copy). This ADR only resolves (1) for
*generation* -- a topic's own initial run isn't instant, so there is still a real window
between "topic accepted" and "cards for tier X exist" where the feed has nothing to serve
for that topic. Whether that window still needs ADR-0006's degraded-mode machinery (and
whether `POOL_LOW`/`POOL_HIGH` still mean anything once there's no ongoing refill to
threshold against) is a feed-serving/read-path question this ADR deliberately leaves open
rather than deciding as a side effect of a generation-side change. `content-model.md`'s
"When the pool cannot satisfy the mix" section is flagged accordingly.

**Update (2026-08-23):** the discoverability half of this question — when a brand-new
topic starts showing up for users who didn't request it — is resolved by
[ADR-0053](0053-topic-live-coverage-threshold.md). The degraded-mode/`POOL_LOW`/`POOL_HIGH`
half, for a *follower's* feed while a topic is still filling in, remains open.

## Consequences

**Easier**

- `GenerationJob` becomes simple: create one row per genuinely-new topic, run it once,
  done. No coalescing lock to reason about, no starvation detection to build.
- No recurring background cost per topic -- the budget is spent once, up front, and never
  revisited, which is easier to reason about against a hard daily quota.
- The pipeline's output is complete (cards **and** questions) the first time a topic
  finishes, rather than quizzes waiting on a separately-triggered question-generation
  path that doesn't exist yet.
- Failure isolation across jobs in one worker pass, without adding any new orchestration
  dependency -- plain `asyncio`, same tool already used for intra-pipeline concurrency.

**Harder**

- The card budget (~750/topic) and question count (~250-300, TBD) have to be genuinely
  large enough that "eventual repeat is fine" holds in practice -- get this wrong and a
  heavily-engaged user exhausts a topic and starts repeating sooner than intended, with no
  refill mechanism to fall back on anymore.
- Linked-tier content-passing needs a real answer for *how much* lower-tier content a
  higher-tier call receives -- a subtopic can have up to 25 cards per tier; passing all of
  them into every higher-tier call is more data per call every time, and needs a concrete
  design (full bodies vs summaries vs a subset) before this is implemented.
- The feed-serving open question above is genuinely unresolved and blocks nothing here,
  but does mean ADR-0006 is now partially stale in a way this ADR doesn't fully clean up.
- `GenerationJob`'s schema needs a migration (drop `kind`'s meaning, change the coalescing
  key) -- not just new code.

**Committed to**

- A topic's pipeline run produces cards **and** questions before it's considered done --
  a topic is never left with cards but no quiz bank.
- Cards go live in the feed as soon as their own subtopic/tier's batch completes, not
  gated on the whole topic (including questions) finishing.
- No `GenerationJob` is ever created for a topic that already has one completed -- one-shot
  means one-shot.
- The worker isolates failures per job (own session, own exception handling); one job's
  failure never silently marks or blocks unrelated jobs in the same pass.

## Alternatives considered

**Keep demand-driven refill, just also add questions.** Rejected: the whole reason to
drop refill is that the fixed budget (cards + questions) is now believed sufficient for
the product's actual usage pattern (repeat-after-exhaustion is acceptable), which makes
the refill machinery pure overhead with nothing left for it to react to.

**Batch the whole worker pass into one `run_generation_pipeline` call (keep the graph's
own multi-topic fan-out for cross-job concurrency), accept coarse failure attribution.**
Considered and rejected in favor of worker-level isolation -- see the reasoning above and
in the earlier discussion this ADR is written from: a batch where one topic's exception
fails four unrelated topics' jobs is a worse default than the small overhead of one
DB session per concurrent task.

**Thread lower-tier content into higher-tier prompts via a separate embedding/summary
step instead of raw content.** Not decided against, just not decided *for* -- this is the
open implementation question flagged in "Harder" above, left for whoever implements this
ADR to resolve concretely.

## Revisit when

- Measured question/card exhaustion rate for real users comes in higher than expected
  (people burn through the fixed budget faster than repeat-is-fine assumed) -- that's the
  signal to reconsider some form of top-up, not to silently widen the budget forever.
- The linked-tier content-passing design (once picked) turns out to blow up prompt size
  in practice for subtopics near the 25-card ceiling.
- The feed-serving open question above gets resolved -- this ADR should be linked from
  whatever ADR resolves it, in both directions, same as this document links back to
  ADR-0006.
