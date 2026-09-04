# Handoff: the IP concurrency ceiling + the in-flight semaphore

**Date:** 2026-09-04 (session ran ~02:00–09:35 UTC)
**Status:** core discovery made and mostly wired; one open question stopped the run.
**Nothing is committed.** 8 files modified in the working tree, `mypy --strict` +
`ruff` clean, targeted tests pass, full `make test` NOT run.

---

## The one thing to internalise

**Google's free-tier edge gateway sheds on CONCURRENCY — how many requests from
this source IP are simultaneously awaiting a response — not on send rate, not on
key count, not on token volume.** Everything else this session found is a
corollary of that.

Evidence, strongest first:

1. **`inflight_sweep.py`** — a worker pool holding *exactly N* requests open at
   once (each worker: call → await full response → next call), 150s sustained per
   N, ~8k-token prompts:

   | N in flight | failure | bare 429s | good calls/s |
   |---|---|---|---|
   | 2 | 1.5% | 0 | 0.85 |
   | 3 | 1.2% | 0 | 1.11 |
   | **4** | **53.6%** | **220** | 1.31 |
   | 5 | 48.4% | 200 | 1.49 |

   A **hard wall between 3 and 4**, not a gradient. Zero perimeter shedding at
   N≤3.

2. **First pipeline run today** used `gemini_dispatch_stagger_seconds = 2.0` — a
   pure send-rate limiter, one request dispatched every 2s (0.5 sends/s, *lower*
   than the clean single-stream probe's rate) with no cap on in-flight. Result:
   **73% failure**, because ~4–10 structured calls (each ~7–17s) were open at
   once.

3. **Direct single-key probes** (`probe.py`/`probe2.py`/`probe3.py`): 12 keys
   from 12 *separate Google projects* fired concurrently all came back with an
   IDENTICAL `retryDelay`, and firing them re-armed a window that had just
   decayed to 0s. The throttle is keyed to the IP, and the
   `GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 500` label it
   carries is boilerplate — those keys were nowhere near 500 requests.

## The second finding: a transient IP penalty that clears at the daily reset

Google's free-tier RPD resets at **~07:00 UTC** (midnight Pacific), not 00:00 UTC.

- **Before the reset** (after ~10h of prior aggressive benchmarking):
  `keycount_probe.py` at a fixed 30 req/min saw 20 keys → 18.9% fail, 30 → 32.2%,
  108 → 42.2% and climbing. A real gradient with key count.
- **After the reset**: re-ran 20/30/50 keys, same harness → **5.6% / 3.3% /
  3.3%**, flat, no gradient. Re-measured twice, consistent.

So sustained aggressive load accrues a soft penalty on the IP that a daily reset
clears. Key count only mattered *while penalised*. On a healthy IP, 50 keys is as
clean as 20 — hence `gemini_active_key_window = 50`.

---

## THE OPEN QUESTION — why the run was stopped

The rolling semaphore of 3 (see "code changes") was wired into the live pipeline
and started at 09:15 UTC. It held **completely clean — 0 × 429 — for ~5 minutes**
(09:16–09:20). Then at **09:21**, exactly when curriculum/planning finished and
full drafting fan-out began, the edge started shedding hard:

```
09:16–09:20   0 × 429/min
09:21        65 × 429/min
09:22       104 × 429/min
09:24       107 × 429/min   (200s stayed ~5/min throughout)
```

83 cards persisted, 338 cards/hr, **0 force-killed cells, 0 terminal errors** —
the safety net held, it just got slow. Run stopped at 09:30.

`inflight_sweep.py` at N=3 stayed clean for its full 150s. The pipeline at
nominal-3 did not. Three hypotheses, not yet distinguished:

- **(a)** Sustained *large-batch* load (structured-output card batches, ~7–17s
  open, thousands of output tokens) re-triggers the transient penalty far faster
  than N=3 small `generate_content` calls do.
- **(b)** The fan-out phase transition briefly pushed *real* concurrency past 3.
  Both the box balancer (card drafts) and the remainder balancer (curriculum /
  gate difficulty+factual judging / verification) draw on the *same* `_inflight`
  semaphore, so this shouldn't be possible — but a burst at fan-out start is
  where to look.
- **(c)** The edge sheds on *connection-seconds* or *bytes in flight*, so 3 big
  17s calls ≠ 3 small 2.5s calls, and the real ceiling for pipeline-shaped calls
  is 2 or even 1.

**`send_rate_probe.py` was written and queued to test the user's alternative
model** — fire N requests, sleep 1s, repeat, *never awaiting them* (pure
send-rate limiting, in-flight floats freely). It records `peak_inflight` /
`mean_inflight`. The user stopped it before it produced results. Read:
`high peak_inflight + low fail` → send rate is all that matters and the
round-trip hold can go; `high peak + high fail` → concurrency is the trigger and
the hold stays.

**The user said "I have some changes in mind" and asked to stop here.** The
decision on the table: rolling semaphore vs. batch-and-pause vs. pure send-rate
limiter, and what N. Wait for the user's direction before changing the mechanism.

---

## Code changes (working tree, uncommitted)

### `apps/api/src/spoin/core/config.py`

| setting | change | why |
|---|---|---|
| `gemini_max_inflight_calls` | **NEW = 3** | hard cap on concurrent HTTP calls; the whole point of this session. Comment carries the `inflight_sweep` table. |
| `gemini_active_key_window` | **NEW = 50** | only N of a box's keys dispatchable at once; sliding window that rotates on *facts* (top rung spent / no budget in window), never on failure rate. |
| `gemini_dispatch_stagger_seconds` | 1.2 → **0.0** | ADR-0086 cross-cell rate stagger; redundant under a concurrency cap and it masked the difference between in-flight settings during tuning. |
| `gemini_initial_dispatch_jitter_seconds` | **removed** (was 3.5) | ADR-0086 fanout jitter; existed to desync a burst the semaphore now bounds directly. |
| `topic_key_box_size` | 34 → **109** | one box = whole pool = one topic at a time. Boxing machinery kept intact (BoxPool still leases/releases/keeps-disjoint); we just never lease a 2nd box. |

### `apps/api/src/spoin/generation/quota.py`

- `_day_start()` now rolls at **`_DAY_RESET_HOUR_UTC = 7`** (07:00 UTC), not
  00:00. Aligns the local `quota_ledger` day with Google's free-tier RPD reset.
  A run launched between 00:00–07:00 UTC was seeding every cell from a
  freshly-rolled empty ledger while Google still counted the previous evening's
  spend → genuine per-day 429s on "fresh" keys. (PST vs PDT drift of 1h is
  accepted as one constant rather than a tz lookup.)

### `apps/api/src/spoin/generation/langchain_impl.py`

- **`_classify_rate_limit`**: a short `RetryInfo` (≤ 60s) now **outranks** a
  `...PerDay...` quotaId → classified per-minute (cell *parked* for the delay,
  not killed). Was: any `perday` string match → `is_daily=True` →
  `on_rate_limited(per_minute=False)` force-sets `rpd_spent = rpd_limit` AND
  flushes a fabricated 500 to `quota_ledger` that the next run seeds from. That
  path destroyed 136 of 204 generator cells in 60 seconds in Benchmark 10.
  New test: `test_classify_rate_limit_trusts_a_short_retry_delay_over_a_per_day_quota_id`.
- **`self._inflight = asyncio.Semaphore(gemini_max_inflight_calls)`** in
  `__init__` (one per process — `GeminiContentGenerator` is an `@lru_cache`
  singleton).
- Wrapped the **single outbound send site** —
  `structured.ainvoke(prompt)` inside `_invoke_with_backoff` — and the
  recovery-probe ping with `async with self._inflight:`. Held for exactly the
  HTTP round trip; a 503 backoff between same-cell retries releases it.
  New test: `test_inflight_semaphore_caps_concurrent_sends`.
- **Removed the ADR-0086 perimeter backoff** (`5.0 + random.uniform(...)` sleep
  on a bare 429). Replaced with: `on_rate_limited(per_minute=True,
  retry_after_s=…)` parks that one cell for Google's stated delay, then
  `continue` — the caller immediately takes the next cell the balancer offers.
  No caller-side sleep.
- Removed now-unused `import random`.

### `apps/api/src/spoin/generation/load_balancer.py`

- **Active-key window**: `_window_of()`, `_rotate_window()`,
  `_top_rung_spent()`, `_rotate_to_any_budget()`. `try_assign` now iterates
  `self._active_keys` (the window) not `self.key_indices` (the whole box).
  `assign` calls `_rotate_to_any_budget` before raising
  `DailyQuotaExhaustedError`, so "this 50-key window is spent" is not mistaken
  for "the 108-key box is spent".
- A **failure-rate-triggered** rotation was built, shipped, and measured live: it
  fired 14 times in 4 minutes on spikes of 60–100% because *every* window it
  moved to spiked too (the throttle is global to the IP). It was **removed** —
  rotation is now facts-only. New tests cover window dispatch, fact-based
  rotation, and window-spent ≠ box-spent.

### `apps/api/src/spoin/generation/pipeline/nodes.py`

- Removed the initial fanout jitter sleep and the inter-round drafting jitter
  sleep (both ADR-0086). Removed now-unused `import random`.

### `apps/api/src/spoin/scan_and_generate.py`

- **Not touched this session.** It was already `M` in the working tree at session
  start (pre-existing 273-line diff). Left as-is.

### Tests

- `test_load_balancer.py` +~80 lines (window behaviour).
- `test_langchain_impl.py` +~87 lines (semaphore cap, PerDay+retryDelay
  classification).
- Passing: `test_load_balancer.py` (44), `test_architecture.py`, and the
  invoke/classification subsets of `test_langchain_impl.py`. **Full DB-backed
  `make test` not run.**

---

## State to resume from

### Config (effective now)
```
gemini_max_inflight_calls        = 3     (rolling semaphore at the send site)
gemini_active_key_window         = 50
gemini_dispatch_stagger_seconds  = 0.0
gemini_send_gap_seconds          = 10.0  (per-cell, dormant — can't bind at 3 concurrent / 100 cells)
topic_key_box_size               = 109   -> max_concurrent_topics = 1
_DAY_RESET_HOUR_UTC              = 7
```

### Database (`spoin_db_2` in `spoin-db-1` — NEVER `docker compose down -v`)
- System Design and Distributed Computing: **646 / 676 cards** (~96%, +166 today)
- PostgreSQL: 168 / 753 (untouched since ~02:16 UTC)
- FastAPI: 29 / 639 (untouched since ~01:53 UTC)
- `quota_ledger`: current provider-day bucket `2026-09-04 07:00:00+00` is
  **empty** (every run was killed before `flush()`). The `2026-09-03 07:00`
  bucket holds 545 rows @ 10 — thinking cells seeded earlier this session to be
  conservative; now "yesterday", harmless. The `2026-09-04 00:00` bucket still
  holds the 28 fabricated `500` rows from Benchmark 10's classification bug —
  harmless (old bucket, `_day_start` no longer resolves there); delete only with
  owner approval.

### Infra
- `spoin-api-1`, `spoin-db-1` up. No worker container. Nothing running.
- `.env` unchanged, 109 keys in `SPOIN_GEMINI_API_KEYS`.

---

## Probe scripts (scratchpad, not committed)

`F:\Temp\claude\E--spoin-bundle\457269a0-845e-4fdd-8cef-3bd2ce5a3109\scratchpad\`

| script | what it measures | key result |
|---|---|---|
| `inflight_sweep.py` | worker pool holding exactly N open, sweep N∈{2..8} | **the 3→4 wall** |
| `send_rate_probe.py` | fire N, sleep 1s, in-flight floats freely — tests "send rate only" | **not run to completion** |
| `batch_pause_probe.py` | fire N, await all N, sleep 1s | superseded by send_rate_probe |
| `keycount_probe.py` | failure vs. #keys in rotation at fixed 30 req/min | transient penalty + reset |
| `gap_sweep.py` | sustained dispatch at fixed inter-send gaps | pacing alone insufficient |
| `ip_limit_probe.py` | tokens/req × concurrency knee grid | 4 conc @ 16k tok = knee (burst) |
| `probe.py` / `probe2.py` / `probe3.py` | direct single-key 429 envelope inspection | IP-level, not project-level |

Run pattern:
```
docker cp <script> spoin-api-1:/app/
MSYS_NO_PATHCONV=1 docker exec spoin-api-1 python -u /app/<script>
```
(`MSYS_NO_PATHCONV=1` stops git-bash mangling the `/app/` path.) Every probe uses
a 60s flat cooldown between arms; none uses a readiness gate any more (a
full-payload readiness gate was tried and added noise).

---

## Throughput reality (so expectations are set)

- `inflight_sweep` N=3: 1.11 good calls/s — but those are ~2.5s bare calls.
- Pipeline structured calls are ~7s → 3 / 7 ≈ **0.43 calls/s ≈ 340–450 cards/hr**
  (last run: 338 cards/hr before it degraded). Roughly the pre-existing baseline.
- Faster is not a pacing problem — the levers are orthogonal:
  1. **Fewer calls per card** (currently ~3.4 — bigger batches, batch-wide
     verification instead of per-card).
  2. **Local generation** — RTX 5070 (12 GB), researched in the conversation:
     Granite 4.1 8B / Qwen3-8B for structured output, prefix-cache the per-topic
     RAG context via SGLang/vLLM, ~5–10k cards/day potential. **The decisive test
     — draft ~20 cards locally, push through the existing Gemini gate, compare
     accept rate — has NOT been run.** That single number decides viability.
  3. **More egress IPs** — each IP gets its own concurrency-3 budget; the only
     lever that raises the ceiling rather than living under it.

---

## First moves for the next session

1. Read this file and `apps/api/src/spoin/core/config.py`'s
   `gemini_max_inflight_calls` / `gemini_active_key_window` comments.
2. `docker exec spoin-api-1 sh -c "cd /app && python -m pytest tests/test_load_balancer.py tests/test_langchain_impl.py tests/test_architecture.py -q"` — confirm green.
3. Ask the user which mechanism change they had in mind (rolling vs.
   batch-and-pause vs. send-rate; and N). Do **not** re-derive the concurrency
   finding — it is settled: ≤3 open is clean in isolation, the open question is
   only why the *pipeline's* large-batch load degraded rolling-3 after 5 minutes.
4. If the plan is "test the send-rate model": finish running
   `send_rate_probe.py` first — it's queued and answers whether the round-trip
   hold is even necessary.
5. Whatever mechanism lands, re-run the single-topic pipeline
   (`docker exec spoin-api-1 python -u -m spoin.scan_and_generate --topics "System Design and Distributed Computing" "PostgreSQL" "FastAPI" --limit 3`)
   and watch the **429/min trend over 15+ minutes**, not just the first 5 —
   degradation-after-5-min is the failure mode to catch.

---

## Superseded by the saga directory (2026-09-04, later)

The batch-and-pause mechanism the open question above was waiting on was chosen by
the owner and tested the same day: it held ~8.5 minutes (vs the rolling semaphore's
~5) and hit the same wall. Full result, and the whole four-week history this handoff
is one chapter of, now lives in **[`docs/gemini-saga/`](../gemini-saga/README.md)** —
specifically [document 4](../gemini-saga/04-the-concurrency-ceiling.md) for the wave
gate and [document 6](../gemini-saga/06-provider-alternatives.md) for where the
project goes next. This file remains accurate as the record of the discovery itself.
