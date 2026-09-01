# Handoff: API-key project audit + restore the 33-key experiment

**Written:** 2026-09-01, mid-session. Branch `main`, HEAD `31df36f` (ADR-0081)
plus later commits (gate batch split, plan self-check). Paste the **Prompt**
block below into a fresh session.

---

## Prompt

> Two jobs, in order.
>
> ### 1. Find which of the 119 Gemini API keys share a GCP project
>
> The full key list is at
> `F:\Temp\claude\E--spoin-bundle\1b43adb3-08d5-4564-a5e0-19a2663d9f5f\scratchpad\.env.backup.full`
> (the `SPOIN_GEMINI_API_KEYS=` line). The **last 33** (indices 86–118) are
> verified-separate projects and ran cleanly-ish in an experiment; the **first
> 86** collapsed under per-minute 429s and mass per-day exhaustion, and the
> working hypothesis is that many of them share GCP projects — so Gemini's
> per-project-per-model RPM/RPD limits are being split across several keys,
> giving nowhere near 86× the rate.
>
> **Ask me first:** do I have a key→project mapping (a spreadsheet, or the
> console projects they were minted in), or working `gcloud` auth? If yes, use
> that:
> - `gcloud projects list`
> - per project: `gcloud services api-keys list --project=<P>` and match by the
>   key string / `uid`.
>
> **If not**, run a behavioural clustering test (write a throwaway script, do
> NOT commit it, keep it off the live pipeline's keys while Backend is still
> generating):
> - For each key in isolation, send ~15–20 rapid `generateContent` calls to
>   `gemini-3.5-flash-lite` and record after how many it first returns 429
>   (its solo per-minute ceiling).
> - Then run keys in pairs/small groups concurrently: if key B starts 429ing
>   far earlier in a group than it did solo, B shares a per-minute bucket with
>   someone in that group. Cluster transitively.
> - Output: groups of key indices that share a project, and the count of
>   genuinely-distinct projects.
>
> Deliverable: a list of distinct-project key indices, and a recommendation on
> whether to **drop** the redundant same-project keys from
> `SPOIN_GEMINI_API_KEYS` (they add contention, not capacity) and set
> `GEMINI_KEY_POOL_SIZE` to the real distinct-project count.
>
> ### 2. Restore the codebase + env from the 33-key experiment
>
> These are TEMPORARY and uncommitted / out-of-band — undo them once step 1 has
> a verdict on the real key count:
>
> - **`apps/api/src/spoin/core/config.py`**: `GEMINI_KEY_POOL_SIZE = 33` →
>   restore to `119` (or to the real distinct-project count from step 1). The
>   `#: TEMPORARY (experiment...)` comment marks it.
> - **`.env`**: `SPOIN_GEMINI_API_KEYS` was truncated to the last 33 keys.
>   Restore the full line from
>   `...\scratchpad\.env.backup.full` (or a de-duplicated subset per step 1).
> - **`generation_job` rows** (live DB `spoin_db_2`, read-only unless I approve
>   writes): Rust `d44ac84e-b731-4d2a-90b1-5acde2fc58d3` and Bhagvad Geeta
>   `2e798451-99e1-4bda-ace2-3a10672da8ef` were set to `status='held'` so only
>   Backend Engineering (`ecbaa024-a39b-44aa-bd9a-ee45e7b910ed`) would run. Set
>   them back to `'pending'` when we want them to resume.
> - **`quota_ledger`**: today's rows were zeroed for the experiment (key
>   re-indexing made them stale). Nothing to restore — it rebuilds — but
>   today's spend history is not real.
> - **Worker container**: running on the 33-key config. After restoring
>   `.env` + `config.py`, recreate it:
>   `docker compose up -d --no-deps --force-recreate worker`.
>
> Nothing above is committed. `main` already has the real work from that
> session (ADR-0079 gags-only, ADR-0080 ascii fetcher, ADR-0081 curriculum
> phase, gate batch split 20/40, gen batch 15 / question batch 35, plan
> self-check, the CockroachDB STRICT note) — leave those.

---

## Why (context, don't re-derive)

- The 119-key run collapsed: ~350 `(key,model)` cells hit provider rate limits,
  ~100 of them genuine per-day exhaustion (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
  limit 500), and the survivors got beaten down to ~1 req/min learned rpm. Root
  cause was (a) shared projects multiplying the per-minute pressure and (b)
  ~45 concurrent subtopic-group branches bursting the gate against tiny per-key
  limits (thinking rpm 5 / rpd 20).
- The 33-verified-separate-key experiment: **no** per-day mass exhaustion at
  start (2 pins vs ~100), Backend reached ~49% in ~40 min — but still ~3:1
  per-minute 429s and per-day pins climbing (2 → 39). So separate keys stop the
  per-day death spiral; they do **not** stop the per-minute burst.

## Still-deferred follow-on work (needs owner decisions, not started)

1. **Global in-flight LLM-call cap** sized to real aggregate RPM (a semaphore,
   ~30–40), so concurrent branches queue instead of bursting.
2. **429 backoff tuning**: shorten the no-`RetryInfo` fallback cooldown (60s →
   ~20s) + exponential + rung-level (not just per-cell) backoff. Touches the
   quota governor — owner said don't casually "fix" it, so propose first.
3. **Verify the ladder `rpd`/`rpm` config** against measured reality (the
   ledger has the numbers).
4. **Fewer topics per worker pass** until `sum(N) <= pool_size` genuinely holds
   with real leases (ADR-0081 gave real widths; the pool just needs to be the
   real distinct-project count).
