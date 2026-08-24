# Generation Pipeline Benchmark: Run 4 & The Redraft-Loop Live Validation

> **Date**: August 24, 2026
> **Scope**: First live production run of the redraft loop (ADR-0057) and the failed-vs-
> rejected stuck-guard fix, against two real topics -- one a brand-new curriculum's first
> pass, one an existing near-target topic being topped up.
> **Status**: Verified Production Proof (Exit Code 0)

Unlike Runs 1-3 ([`generation-pipeline-test-run.md`](generation-pipeline-test-run.md),
[Run 2](generation-pipeline-run-2-benchmark.md), [Run 3](generation-pipeline-run-3-benchmark.md)),
this was not a scaling exercise -- two topics, not five, run manually from a laptop mid-code-
review session, not a batch blitz. The point of this run was to prove, against real
`spoin_db` data and real Gemini calls, that the same-day code changes actually behave the way
their commit messages claim.

---

## 1. What this run was actually testing

Two fixes landed on `main` earlier the same day and needed a live check, not just unit tests:

1. **[`e0a25a7`](https://github.com/anubhav-qt/spoin_bundle/commit/e0a25a7)** -- the redraft
   loop (ADR-0057) and the fix for the overshoot bug (a rerun used to draft a whole fresh
   `target_cards`-sized batch instead of just the deficit).
2. **[`732218f`](https://github.com/anubhav-qt/spoin_bundle/commit/732218f)** -- splitting the
   redraft loop's stuck guard into `stuck_rounds` (gate genuinely rejecting) vs
   `no_verdict_rounds` (the generator call itself returning nothing), so a quota-exhausted run
   doesn't get misread as a content-quality failure.

Both got proven live, not just unit-tested:

- **Deficit-bounded drafting, confirmed live:** `python -m spoin.generate_topics "How
  Everyday Things Work" "Bhagvad Geeta in Easy Language::..."` was run twice within the same
  session. Both topics matched onto **existing** topics already sitting close to target
  (`existing=17 target=18`, `existing=13 target=16`, etc., straight from the log) -- the run
  drafted only the small remaining deficit per tier, never a fresh full batch on top. This is
  the exact scenario the overshoot bug used to break.
- **failed-vs-rejected split, confirmed live:** the Gita topic's final report line reads
  `59 card(s) accepted, 266 rejected, 44 failed (not judged -- e.g. quota exhaustion), 58
  question(s) accepted, 0 rejected` -- two genuinely different numbers, not folded into one.
  The 44 "failed" is a real quota/timeout artifact from this run (see §4) sitting alongside
  266 real, judged gate rejections without contaminating each other's count.

## 2. Run narrative

Two invocations, same session:

- **Run A (manually stopped mid-way):** started to confirm the deficit-bounded fix on a
  rerun. Confirmed working (existing counts respected, no overshoot), then stopped on
  request partway through -- everything persisted up to that point stayed committed (the
  pipeline gates+persists per round, not at the end, so a stop never loses completed work).
- **Run B (completed clean):** `spoin-api-run-1cdaf28c79d5`, started 15:07:17, finished
  15:40:49 -- **33m 32s**, exit code 0, no manual intervention.

## 3. Final per-topic results (Run B, from the pipeline's own report)

```
Topic                            | Accepted | Rejected | Failed | Questions Accepted | Questions Rejected
----------------------------------+----------+----------+--------+---------------------+--------------------
How Everyday Things Work         |       26 |        3 |      0 |                  26 |                   0
Bhagvad Geeta in Easy Language    |       59 |      266 |     44 |                  58 |                   0
```

`Bhagvad Geeta`'s 266 rejections were near-entirely `verification`-stage (advanced-tier
cards repeatedly judged too introductory -- "high-level summary," "Made Easy" framing, basic
Python pseudo-code where deep textual analysis was expected) -- the redraft loop kept
drafting replacements round after round rather than accepting the shortfall, which is exactly
what it exists for. The 44 "failed" entries are whole-batch `correct_cards call failed:`
errors and a `504 DEADLINE_EXCEEDED` on `gemini-3.7-flash` -- genuine call failures, correctly
kept out of the rejection count.

## 4. Peak throughput

Two different numbers, depending on what's being measured:

- **All-time peak (`spoin_db`, verified against real, non-seeded card timestamps):** **218
  cards in one minute**, 2026-08-24 13:17 -- the Gita topic's original full-curriculum first
  pass (41 subtopics drafting concurrently), several hours before this run. ~3.6 cards/sec
  sustained for that minute.
- **This run's peak (Run B, topping up already-substantial topics):** **24 cards/minute** at
  15:13, including a 20-card burst in a single second (15:13:36). Lower than the all-time
  peak because far fewer subtopic-tiers had a real deficit to fill concurrently -- a top-up
  run's fan-out width is bounded by how many tiers are actually under target, not by total
  subtopic count.

## 5. Live corpus snapshot, `spoin_db` (2026-08-24, post-run)

```
                        canonical_name                         | active_cards
---------------------------------------------------------------+--------------
 Operating Systems                                              |        1739
 Docker                                                          |        1641
 Computer Networking                                             |        1283
 System Design & Distributed Systems                             |         756
 Bhagvad Geeta in Easy Language                                  |         753
 German (Language)                                               |         715
 Kubernetes                                                      |         701
 PostgreSQL                                                      |         696
 How Everyday Things Work                                        |         691
 The Epic of Gilgamesh                                           |         655
 FastAPI                                                         |         625
 Claude Code (Becoming a 10x Developer)                          |         619
 Gym (Physical Fitness)                                          |         613
 10M Air Pistol Shooting                                         |         589
 Building a Successful Kurtis Business in e-commerce for India   |         543
 Study Abroad (Full Guide)                                       |         503
 Current AI Capabilities and Scope                               |         476
---------------------------------------------------------------+--------------
 TOTAL LIVE ACTIVE CARDS                                        |       13,598
```

17 topics, all with `is_seeded = false` -- no mock/fixture data, matching CLAUDE.md's "old
mock/seeded testing fixtures were completely purged" rule.

## 6. Quota ledger, today (2026-08-24)

```
model                    | active keys | requests spent today
--------------------------+-------------+----------------------
gemini-3.5-flash-lite     |           7 |                   983
gemini-3.6-flash          |          16 |                   353
gemini-3.7-flash          |          15 |                   348
gemini-3.5-flash          |           8 |                   144
gemini-3.1-flash-lite     |           3 |                    49
gemini-3-flash-preview    |           1 |                     3
```

One `gemini-3.5-flash-lite` key hit its 500 RPD ceiling mid-run (15:10:04) and the ladder
rotated to the next key without dropping a draft -- same fallback behavior Run 3 documented,
still holding.

## 7. Same-day context: first public validation run

Not a generation-pipeline metric, but the same day this run happened, the product got its
first outside-world feedback -- three Reddit threads (r/sideprojects, r/SideProject,
r/ProductivityHQ) and one unprompted "where can I download this?" See
[`docs/product/2026-08-24-first-public-validation-run.md`](../product/2026-08-24-first-public-validation-run.md)
for the actual threads; not duplicated here since it's a different kind of signal than a
throughput number.

## 8. Conclusion

Run 4 doesn't move any of Run 3's scale records -- it was never meant to. What it proves is
narrower and, for today, more important: the redraft loop and the failed-vs-rejected fix
both do, against real `spoin_db` data and real Gemini calls, exactly what their commit
messages and ADR-0057 claim. A tier that gets rejected gets redrafted, not silently left
short. A tier that fails to even get a verdict is distinguished from one the gate actually
rejected, in both the internal stuck-guard logging and the final report. A rerun on an
already-populated topic drafts only its real deficit, never a duplicate full batch.
