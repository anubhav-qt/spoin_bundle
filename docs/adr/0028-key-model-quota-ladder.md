# ADR-0028: Per-key-per-model quota grid, with a two-pool model fallback ladder

- **Status:** Accepted (amended by [ADR-0029](0029-questions-join-generator-pool.md))
- **Date:** 2026-08-17
- **Deciders:** Anubhav
- **Resolves:** [ADR-0008](0008-local-gpu-generation.md)'s open question on cloud model choice
  (the *rotation mechanism*, not the specific model ids — those are still a first draft, see
  that ADR's updated "Open question" section)
- **Amended by:** [ADR-0029](0029-questions-join-generator-pool.md) — `generate_questions`
  moved from the thinking pool to the (renamed) generator pool, below. The table's
  "questions in thinking" row and its reasoning are superseded; the rest of this ADR
  (the grid mechanism, RPD/RPM split, requeue-on-exhaustion) is unchanged.

## Context

`generation/quota.py`'s original `QuotaGovernor` rotated across `SPOIN_GEMINI_API_KEYS`
against one fixed daily target, on the assumption that each key is its own quota pool.

Checking that assumption against the actual Gemini API docs surfaced two things, both
load-bearing for how the governor needs to work:

1. **Rate limits are per Google Cloud *project*, not per API key.** Multiple keys minted
   under the same project share one pool — rotating "keys" that all belong to one project
   buys nothing. Every entry in `SPOIN_GEMINI_API_KEYS` only helps if it is a genuinely
   separate project.
2. **Rate limits are also per *model*, independently.** Exhausting `gemini-2.5-flash`'s
   daily quota does not touch `gemini-3.5-flash`'s — they are wholly separate buckets, on
   the same key. A rate-limit page for one project (screenshotted during this
   conversation) shows ten-plus models each with their own RPM/TPM/RPD figures.

The old governor modeled neither of these: one key = one pool, one model, one flat daily
number. It also never enforced RPM at all — `quota_rpm` existed in `Settings` but nothing
read it.

## Decision

**The quota governor tracks a grid: `(key_index, model)` → today's spend**, not a flat list
of keys. `QuotaLedger` rows are keyed `backend=f"gemini:{key_index}:{model}"` instead of
`f"gemini:{key_index}"`.

**Two independently-rotating pools**, one `QuotaGovernor` instance each, inside
`GeminiContentGenerator`:

| Pool | Calls | Ladder |
|---|---|---|
| **thinking** | `generate_curriculum`, `match_topics`, `judge_difficulty`, `generate_questions`, `grade_free_text` | baseline Flash models, newest→oldest |
| **cards** | `generate_cards` only | "lite" Flash models, newest→oldest |

> **Superseded by [ADR-0029](0029-questions-join-generator-pool.md):** `generate_questions`
> moved out of the thinking row into the cards row, and the pool itself was renamed
> `cards` → `generator` since it's no longer card-specific. Kept here, not edited, per this
> repo's "don't edit history" ADR rule — read ADR-0029 for the current assignment and why.

The split follows the rule already established across this codebase (content-model.md, ADR-
0008): the thinking pool covers every call where a weak model has a real consequence — a
bad curriculum, a bad topic match, a bad judgment, a bad quiz question, a bad grade. Card
writing is pure prose, independently checked by the quality gate afterward, so it gets the
cheap high-volume ladder instead of competing with the thinking pool's budget.

**Search order: model first, then key, and it never waits.** For a call in a pool, walk the
ladder top-down (strongest model first); for each model, try every configured key in order.
The first `(key, model)` cell with room — on both RPD and RPM — is used immediately. A model
is only skipped once *every* key is exhausted for it; a key that's merely RPM-capped this
second is skipped in favor of the next key or model, never slept on. Only once the entire
grid (every key × every model in the pool) is exhausted does `acquire()` raise
`QuotaExhaustedError`.

Total daily capacity for a pool is therefore *(each model's RPD) × (number of configured
keys)*, summed down the ladder — adding a key (from a genuinely separate project) adds a
full row to the grid, not a fraction of one.

**RPD is persisted, RPM is not.** RPD has to survive across the worker's separate cron
passes within the same day, so it stays in `QuotaLedger` (Postgres). RPM only needs to
survive one worker run — the worker is a short-lived batch pass (ADR-0003 §3), not a
persistent process — so it lives in an in-process sliding-window dict keyed by
`(key_index, model)`, reset every run. This avoids a DB round-trip per request purely to
enforce a per-minute ceiling.

**Quota exhaustion is not job failure.** `apps/worker/__main__.py` now catches
`QuotaExhaustedError` specifically (before the generic `except Exception`) and requeues the
`GenerationJob` as `pending` rather than marking it `failed`. `run_generation_pipeline` is
already idempotent per topic (ADR-0026) — a job that stops partway because the whole grid is
spent for the day picks up exactly where it left off once a later cron pass runs after
quota resets. Before this ADR, `quota.py`'s own docstring already claimed this was "a real,
expected outcome to degrade gracefully from" — the graceful part was never actually wired
up at the job boundary; it is now.

## Consequences

**Easier**

- Adding a key from a new project actually multiplies capacity, predictably, instead of
  silently doing nothing if it happens to share a project with an existing key.
- Quota exhaustion mid-run no longer looks identical to a real bug in `GenerationJob.status`
  — a `pending` job that failed for capacity reasons is distinguishable from a `failed` one
  that didn't.
- RPM is now actually enforced, closing a real gap (the setting existed, nothing read it).

**Harder**

- Two `QuotaGovernor` instances and two ladders to keep in sync with whatever the actual
  free-tier limits are on a given key — these are hand-copied from a rate-limit page, not
  fetched from an API, so they can drift as Google changes free-tier terms.
- The RPM window is in-process only, so it does NOT protect against concurrent Python
  processes hitting the same key (e.g. a manually-run CLI script racing the cron worker) —
  only the RPD figure (DB-backed) is safe across processes. Acceptable today because nothing
  runs concurrently with the worker in practice; would need to move server-side if that
  changes.
- A job that keeps hitting `QuotaExhaustedError` every cron pass (because the day's quota is
  genuinely gone) churns: requeued, reclaimed 15 minutes later, exhausted again, requeued
  again — wasted claim-and-fail cycles until quota actually resets at midnight PT. No backoff
  is implemented; deferred as a minor inefficiency, not a correctness problem.

## Alternatives considered

**Keep one flat daily number per key, ignore the per-model reality.** Simplest, but
undercounts real capacity badly — a key genuinely has ~5 independent 20/day buckets across
Flash variants, not one shared 20/day number, so this alternative would exhaust "quota" and
sit idle while 4/5 of the real budget went untouched.

**Block/sleep when the top choice is rate-limited, instead of falling through the grid.**
Rejected: there is almost always another `(key, model)` cell with room; sleeping wastes wall
clock the worker doesn't have much of (a 15-minute cron slice) when a fallback is sitting
right there.

**Persist RPM to Postgres like RPD.** Rejected for now: adds a DB write to every single call
purely to enforce a per-minute ceiling that only matters within one short-lived worker
process anyway. Revisit if a second concurrent process starts sharing a key (see Harder,
above).

## Revisit when

- A second process (a manual CLI run, a second worker) needs to share a key concurrently
  with the cron worker — the in-process-only RPM window stops being safe at that point.
- The hand-copied ladder figures drift from what a key's project actually allows (a 429 from
  a cell this grid believes has room is the signal).
- The requeue-churn cost (see Harder) becomes worth fixing with an actual backoff /
  "don't reclaim before tomorrow" signal on the job row.
