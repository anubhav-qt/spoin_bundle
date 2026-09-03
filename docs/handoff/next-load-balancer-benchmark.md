# Handoff: benchmark the ADR-0084 load balancer on a clean pool

**Written:** 2026-09-03, end of session. Branch `main`, HEAD `07b87f8`
(ADR-0084 load balancer + the fixed per-cell send gap). `make check` green.
Paste the **Prompt** block into a fresh session.

---

## Prompt

> The ADR-0084 in-memory load balancer is on `main` and its mechanism is proven
> correct (deterministic send rate, even round-robin — see "What we already
> know"). Two benchmarks failed with 85–95% 429 rates, but the pool was
> contaminated: ~6,900 lite-tier calls were burned earlier today (mostly a
> 3.5-hour orphaned `generate_topics` run) and 11+ `(key,model)` cells hit their
> 500/day cap. **Neither run was a clean test.** Your job is to get one.
>
> ### Path A — re-benchmark on a fresh daily budget (do this first)
>
> 1. Confirm the Google free-tier daily reset has passed (~00:00
>    America/Los_Angeles ≈ **07:00 UTC**). Sanity-check:
>    `docker compose exec -T db psql -U spoin -d spoin_db_2 -tA -c "select coalesce(sum(requests_spent),0) from quota_ledger where day=date_trunc('day',now())"`
>    — should be low (hundreds, not thousands).
> 2. Re-run benchmark 2 **verbatim**, config unchanged (`topic_key_box_size=75`
>    → one box, `gemini_send_gap_seconds=4.0` → 4s per `(key,model)` cell):
>    ```
>    docker compose exec -T api sh -c 'python -m spoin.generate_topics "Generative AI" 2>&1 | tee /tmp/bench3.log'
>    ```
>    Run it with `run_in_background`. **Immediately** grab the in-container PID
>    (`docker compose exec -T api bash -c 'for p in /proc/[0-9]*; do tr "\0" " " < $p/cmdline; echo; done | grep generate_topics'`)
>    — killing the bash task does NOT kill it (see gotchas).
> 3. Let it run. The fan-out storm (if any) starts ~4 min in. Check at T+5 and
>    T+10 min: `grep -c '429 Too Many' /tmp/bench3.log` vs
>    `grep -c 'HTTP/1.1 200' /tmp/bench3.log`, and Generative AI's card count
>    (base 138).
> 4. **Decision, from the first ~10 min:**
>    - **429 rate < ~20%, cards climbing** → 4s works on a clean pool; today was
>      pure daily exhaustion. Next: drop `topic_key_box_size` to 34, re-run with
>      two topics, confirm concurrency is safe, then finish the topic queue
>      (`docs/notes/generation-queue.md`).
>    - **429 rate still > ~50% on a fresh day** → the real per-minute ceiling is
>      below 15/min for these keys → shared projects. Either widen the gap
>      (`gemini_send_gap_seconds` 4 → 12–15) and re-test, or go to Path B.
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
- **Why the pool is contaminated:** `gemini-3.5-flash-lite` 4,766 req today with
  **7 keys at the 500/day cap**; `gemini-3.1-flash-lite` 2,122 with 4 at cap.
  Most of that is a 3.5-hour orphaned `generate_topics` (Physical Fitness + Carl
  Jung) run that survived a `TaskStop`, ran on pre-ADR-0084 code, and was
  migrated out from under before being killed. No corruption resulted; PF got to
  ~504 cards, CJ to ~407.
- **Google returns scopeless `RESOURCE_EXHAUSTED`** on ~99% of 429s (580 vs 2
  self-identified as per-day this run), so per-minute vs per-day is
  indistinguishable at the wire. This is the standing ADR-0060 problem.
- **Daily reset:** Google free tier resets at ~midnight America/Los_Angeles.
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
