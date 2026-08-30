# Generation Pipeline Benchmark: Run 7 -- One Topic, Under 20 Minutes

> **Date**: August 30, 2026
> **Scope**: A single topic (CockroachDB) generated end to end on the
> [ADR-0074](../adr/0074-key-per-subtopic-scheduling.md) scheduler -- one API key per
> subtopic group, and question generation moved to a topic-wide phase at the fan-in.
> **Status**: Verified Production Proof (Exit Code 0, 100% coverage, 35/35 subtopic-tiers).
> First run on the key-claim scheduler.

Runs 1-6 ([test run](generation-pipeline-test-run.md),
[2](generation-pipeline-run-2-benchmark.md), [3](generation-pipeline-run-3-benchmark.md),
[4](generation-pipeline-run-4-benchmark.md), [5](generation-pipeline-run-5-benchmark.md),
[6](generation-pipeline-run-6-benchmark.md)) all ran on per-CALL key selection: every
request scanned the whole `(key, model)` grid for the least-spent cell. Run 7 is the first
on per-GROUP key ownership. The headline is wall-clock -- **18m 50s for a 492-card topic**,
against a 30-50 minute average for a comparable topic before.

---

## 1. The run

| | |
|---|---|
| Topic | CockroachDB |
| Subtopic-tiers | 35, in 18 groups (3 single-tier, 13 two-tier, 2 three-tier) |
| Cards accepted | **492** (10-19 per tier, mean 14.1) |
| Cards rejected | **6** -- all `verification`; zero structural, zero near-duplicate |
| Generator failures | **1** (a call that returned no verdict -- not a rejection) |
| Questions accepted | **292** |
| Questions rejected | 1 |
| Exit | 0, all 35 tiers at 100% |

Rejected and failed are counted apart, as always (CLAUDE.md): 6 drafts were judged and found
wanting, and 1 call never came back with a verdict at all. A 6/498 rejection rate is far
below any previous run's, which is worth reading with suspicion rather than celebration --
see §5.

## 2. Wall clock, from the row timestamps

Every figure below is `min`/`max` of `created_at` on the rows themselves, not a stopwatch:

```
09:49:09   topic row created
09:50:09   curriculum_generated_at          (+1m 00s)
09:52:46   first card persisted             (+2m 37s -- planning + first drafts)
10:06:12   last card persisted              (card phase: 13m 26s)
10:06:12   first question persisted         (+9 MILLISECONDS)
10:07:59   last question persisted          (question phase: 1m 47s)
           ------------------------------------------------
           total: 18m 50s
```

**The 9ms gap between the last card and the first question is ADR-0074's fan-in gate,
visible in the data.** Questions cannot start until every group has cleared its card bar;
the instant the last one did, all 35 tiers' question units started at once. 292 questions in
1m 47s is what that phase looks like when it is not competing with card generation for keys.

Against previous runs: a comparable single topic took **30-50 minutes**. The card phase
itself is where the time went, and where the concurrency now is.

## 3. Key scheduling: the ceiling was the curriculum, not the pool

Mid-run, a claim-wait line reported `15 key(s) held by other work, 17 unclaimed`. With the
claim doing the logging that is 16 keys in use out of 33 -- and the pipeline was at full
stretch. The fan-out unit is the subtopic **group**, not the subtopic:

| tiers in group | groups |
|---|---|
| 1 | 3 |
| 2 | 13 |
| 3 | 2 |

18 groups, so **18 is the concurrency ceiling for this topic, not 35 and not 33**. Tiers
inside a group are a data dependency, not parallel work -- a higher tier's `generate_cards`
call receives the lower tier's actual card bodies as `builds_on` -- so they run sequentially
and could never have used separate keys at the same time.

The 17 idle keys are not waste. They are the fallback pool ADR-0074's step 3 moves a group
onto when its own key runs out of preferred rungs, and they carry the day's RPD. But it does
mean the ADR's "parallelism = key count" only binds once a curriculum produces ≥33 groups,
which this one did not come close to. **At current curriculum widths the 33-key pool is
sized for RPD and fallback, not for concurrency.**

## 4. Quota: the ladder that actually ran was NOT the one in the code

Today's ledger, across the whole day:

| model | pool | keys used | requests | min/key | mean | max/key |
|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` | generator | 33 | 588 | 9 | 17.8 | 27 |
| `gemini-3.6-flash` | thinking | 28 | 141 | 1 | 5.0 | 16 |
| `gemini-3.1-flash-lite` | generator | 33 | 22 | 0 | 0.7 | 4 |
| `gemini-3.7-flash` | thinking | **0** | **0** | -- | -- | -- |

**`gemini-3.7-flash` was never touched, and it should have been first.** No
`model_unavailable` row explains it. The cause was found while writing this document:
`docker-compose.yml` set `SPOIN_GEMINI_THINKING_LADDER` with its own hardcoded default that
was still 3.6-first, so the ladder restored in `core/config.py` was overridden by the
environment for anything running under the `api` service -- and only that service set the
variable, so `api` and `worker` resolved the same setting differently. Fixed in the same
commit series as this document.

**So Run 7's numbers describe the 3.6-first ladder. The 3.7-first restoration remains
unproven, and the next run is its first real test.** Everything else here -- the claim
scheduler, the fan-in question phase, the wall clock -- is unaffected; only which thinking
model served the calls.

Two things the numbers do show clearly:

- **Load spread evenly.** 33/33 keys used on the generator pool, 9-27 requests each. The
  claim scheduler does not concentrate load on low-numbered keys, which was the ADR-0065
  failure mode (key 0 at 380/500 while keys 10-32 sat at 15/500).
- **Thinking is cheap at this shape.** 141 thinking requests against 610 generator requests.
  The 20 RPD-per-cell thinking ceiling never came near binding for a single topic: 141
  requests against a 560-request ordinary-rung budget (28 keys × 20) on one model alone.

## 5. What NOT to conclude

- **6 rejections is not proof of a 6× quality jump.** Runs 5 and 6 rejected far more. This
  run also used a different thinking model than intended (§4) for the correction and
  verification passes, so the gate was doing its judging on `gemini-3.6-flash` throughout.
  A gate that rejects almost nothing is as worth investigating as one that rejects too
  much -- confirm against read cards before treating 1.2% as the new baseline.
- **18m 50s is one topic, one shape.** 18 groups, 35 tiers, an uncontended 33-key pool, and
  a worker with nothing else queued. A topic wide enough to exceed 33 groups, or a second
  job in the same pass, will look different.
- **Questions in 1m 47s benefited from an empty pool.** The question phase ran with the card
  phase entirely finished, so all 33 keys were free to it. That is by design, not luck --
  but it is not a figure that survives two topics generating at once, which ADR-0073
  currently prevents anyway.

## 6. Live corpus, `spoin_db_2` (2026-08-30, post-run)

| | |
|---|---|
| Topics | 61 |
| Subtopic-tiers | 580 |
| Active cards | 9,464 |
| Questions | 6,303 |

## 7. Conclusion

The scheduler change did what ADR-0074 predicted and one thing it did not.

**Predicted:** concurrency became a property you can state -- one group, one key -- and the
run got faster rather than slower despite giving up the per-call packing ADR-0047 fought
for. Load spread across all 33 keys. The fan-in question phase worked, and its 9ms handover
is the cleanest evidence available that the gate is where the ADR says it is.

**Not predicted:** the run silently used the wrong thinking model, because a compose default
outranked the code. The lesson generalises past this setting -- a value with a default in
BOTH `core/config.py` and `docker-compose.yml`, set for one service and not another, is a
setting whose effective value nobody can read off the source. Worth a sweep of the other
`${VAR:-default}` entries in compose against their `Settings` fields before trusting any of
them.
