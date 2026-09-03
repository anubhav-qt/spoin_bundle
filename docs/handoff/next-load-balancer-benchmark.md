# Handoff: benchmark the ADR-0084 load balancer on a clean pool

**Written:** 2026-09-03, end of session. Branch `main`, HEAD `07b87f8`
(ADR-0084 load balancer + the fixed per-cell send gap). `make check` green.
Paste the **Prompt** block into a fresh session.

---

## Prompt

> The ADR-0084 in-memory load balancer is on `main` and its mechanism is proven
> correct (deterministic send rate, even round-robin — see "What we already
> know"). Two benchmarks failed with 85–95% 429 rates.
>
> **KEY FINDING (2026-09-03, owner-verified):** the owner checked 8 keys from 8
> separate Google accounts/projects directly against Google's dashboards —
> **more than HALF the daily quota is left even on the top thinker models (3.8,
> 3.7-flash), and ≲20 requests have gone to the flash-lite models all day.** So
> the "7 keys at 500/day cap" in our `quota_ledger` is **stale garbage** written
> by the pre-ADR-0084 orphan run's old-code accounting — NOT real exhaustion.
> The 429 storms are **per-minute throttling**, and 15/min per cell (the old 4s
> gap) is above the real ceiling. A `gemini_send_gap_seconds = 10.0` (6/min per
> cell) probe was set at end of session; re-measure from there.
>
> ### Path A — probe the real per-minute ceiling (do this first; no reset needed)
>
> The daily budget is fine (see KEY FINDING), so this is purely about finding a
> send rate Gemini accepts. `gemini_send_gap_seconds` is already `10.0` on main.
>
> 1. Run benchmark 3 (`topic_key_box_size=75` → one box, `gemini_send_gap_seconds=10.0`
>    → 6/min per cell):
>    ```
>    docker compose exec -T api sh -c 'python -m spoin.generate_topics "Generative AI" 2>&1 | tee /tmp/bench3.log'
>    ```
>    `run_in_background`. **Immediately** grab the in-container PID
>    (`docker compose exec -T api bash -c 'for p in /proc/[0-9]*; do tr "\0" " " < $p/cmdline; echo; done | grep generate_topics'`)
>    — killing the bash task does NOT kill it (see gotchas).
> 2. The fan-out is ~4 min in (after the 60s warm-up + planning). Check at T+5
>    and T+10: `grep -c '429 Too Many' /tmp/bench3.log` vs
>    `grep -c 'HTTP/1.1 200' /tmp/bench3.log`, and Generative AI's card count
>    (base 138).
> 3. **Decision, from the first ~10 min:**
>    - **429 rate < ~15%, cards climbing** → 6/min per cell is under the real
>      ceiling. Narrow it back toward 4–6s to reclaim throughput, re-measure,
>      then drop `topic_key_box_size` to 34 for a two-topic concurrency test, then
>      finish the queue (`docs/notes/generation-queue.md`).
>    - **429 rate still > ~40%** even at 6/min → the keys share projects (several
>      map to one per-minute bucket, so the effective rate per bucket is 2–4×
>      what the balancer thinks). Go to Path B.
>    - Watch for a run that **spin-waits without terminating** (bench 2 did this
>      — a sparse trickle of 200s kept resetting the throttle streak). Kill it;
>      that itself is the "keys are throttled" signal.
>
> ### Path B — finish the key→project audit (the real fix if A confirms sharing)
>
> The 75-key pool was never fully de-duplicated (Phase B of
> `docs/handoff/next-key-projects-and-experiment-restore.md` — read its Job 1).
> **Ask me first** whether I have `gcloud` auth or a key→project mapping — that
> skips the probe entirely. Otherwise, right after the daily reset (needs
> per-minute headroom): throwaway probe (do NOT commit), ~25 concurrent calls
> per key, cluster keys whose 429-onset collapses when run together. Then prune
> `.env`'s `SPOIN_GEMINI_API_KEYS` to ~1 key per distinct project and set
> `gemini_send_gap_seconds = ceil(60 / measured_rpm)`. Re-run benchmark 2.
>
> Report the 429 rate, the card delta, and which path the evidence points to.
> Do not tune the balancer further until a clean benchmark exists.

---

## What we already know (do not re-derive)

- **The balancer mechanism is not the problem.** With `gemini_send_gap_seconds`
  set, every send to a `(key,model)` cell is ≥4s apart (≤15/min/cell, a
  constant), and `_CellState.dispatched` round-robins so the ledger shows load
  spread dead-evenly across all 75 keys. The trailing-60s window and the
  learned-rpm ceiling are **shelved** while a gap is set (`_paced`). So a 429 at
  this rate is exogenous — Gemini, not us. That certainty is the whole point of
  the fixed-gap design.
- **Benchmark 1** (`b542r0bob`, box 34 × 2 topics): 95% 429,
  `AllCellsThrottledError` in 10 min, +87 cards (Air Pistol only).
- **Benchmark 2** (`bsiol3yaa`, box 75 × 1 topic, 4s gap): 85% 429, successes/min
  collapsed 43 → 29 → 3 → 4, **+0 cards**, spin-waited until killed (never a
  terminal error — the sparse trickle of 200s kept resetting the throttle
  streak; a "no accepted cards in N minutes → give up" guard is a possible
  follow-up).
- **Our `quota_ledger` over-counts.** It showed `gemini-3.5-flash-lite` 4,766
  req today / 7 keys at the 500/day cap — but Google's own dashboards (8
  separate accounts) show ≲20 flash-lite requests and >50% thinker quota left.
  The 500s are stale rows from the pre-ADR-0084 orphan `generate_topics`
  (Physical Fitness + Carl Jung) run — 3.5 h on old code that survived a
  `TaskStop`, wrote `requests_spent = 500` on its own 429 classification, and
  was migrated out from under before being killed. No corruption; PF reached
  ~504 cards, CJ ~407. **A follow-up worth doing:** zero or reconcile today's
  `quota_ledger` rows so seeds are honest (owner approval — it's a write to
  `spoin_db_2`).
- **Google returns scopeless `RESOURCE_EXHAUSTED`** on ~99% of 429s, so
  per-minute vs per-day is indistinguishable at the wire (standing ADR-0060
  problem). But the owner's dashboard check settles it for now: **it's
  per-minute.**
- `.env` (gitignored) holds 75 keys: ~36 verified-distinct + 33 known-good + ~6
  partially-pruned representatives of a 45-key shared-project block.
- Migration `c4d5e6f708a9` is **applied** to `spoin_db_2`. alembic head is
  `c4d5e6f708a9`. Neon backup synced pre- and post-migration.

## Gotchas

- **`TaskStop` on a background `docker compose exec` does NOT kill the
  in-container process.** It orphans (PPid 0) and keeps writing. Always
  `docker compose exec -T api bash -c 'kill -KILL <pid>'` and re-scan `/proc` to
  confirm. This has bitten twice.
- **`generate_topics` output is block-buffered** through `docker exec -T` (no
  `PYTHONUNBUFFERED`). The log file lags minutes behind reality — trust the DB
  (`card` counts, `quota_ledger`) for live progress.
- Do not `alembic downgrade` / `docker compose down -v` / touch `spoin_db_2`
  destructively — CLAUDE.md, four prior wipes.

## Current corpus state (2026-09-03)

| Topic | cards | target | note |
|---|---|---|---|
| Generative AI | 138 | 578 | benchmark topic — 0 progress so far |
| Physical Fitness | ~504 | 679 | orphan run got it here; needs question phase |
| Carl Jung's Philosophy | ~407 | 628 | same |
| 10M Air Pistol Shooting | ~392 | 462 | benchmark 1 got it here |

Full queue: `docs/notes/generation-queue.md`. The debugging arc:
`docs/notes/rate-limit-load-balancer-debugging.md`.
