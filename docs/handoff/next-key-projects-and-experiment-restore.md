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

## RESULTS — 2026-09-01 session (both jobs actioned)

### Job 2 (restore) — done by the session that wrote this handoff
`config.py` `GEMINI_KEY_POOL_SIZE` back to 119, `.env` back to the full list,
worker container down, Backend `pending` / Rust + Geeta `held`. Then a later
session **removed `GEMINI_KEY_POOL_SIZE` and its exactness validator entirely** as
part of reverting ADR-0078 (see below), so `.env` no longer has to be an exact
length.

### Separate but same session — pipeline reverted to the Run 8 regime
Commit `424142e` on `main` (pushed): reverted **ADR-0078** (topic-parallel key
leases) and **ADR-0081** (curriculum pre-admission phase); back to the ADR-0073
sequential single-topic worker + ADR-0074 per-subtopic-group keys that Run 8 ran
unattended. Kept ADR-0079/0080 (ascii), the bigger batches (gen 15 / q 35), the
gate pass-2 split, the mermaid guard, the repair lane. ADR-0078/0081 kept as
tombstones. `make check` green.

### Job 1 (key→project audit) — behavioural probe run, no gcloud/mapping was available
Throwaway probe: `…/4aed9d94-…/scratchpad/key_cluster_probe.py` (subcommands
`A` solo-ceiling burst, `B` group-contention, `analyze`; `--model` overridable).
Method that worked: fire **25 concurrent calls** at one key (sequential drip was
~12 s/call — hours). Free-tier flash-lite per-project ceiling ≈ **16 req/min**.
A shared per-minute bucket can't refill 0→16 in the 6 s inter-key gap, so a
sequential tight-gap A-scan already proves *non*-sharing where every key reads 16.

**Scanned keys 0–85** (the suspect set; last 33 taken as known-good per owner):

| Set | Original indices | Verdict |
|---|---|---|
| Dead — HTTP 401 "service account deleted or disabled" | 17, 18, 19, 20, 21 | **Removed from `.env`** |
| Distinct healthy projects (clean ~16 ceiling, non-sharing) | 0–16, 22–35, 37, 38, 73, 78, 85 — 36 keys | Keep |
| Shared-project block | 36, 39–72, 74–77, 79–84 — 45 keys | **Staged out of `.env`** (commented `# SPOIN_GEMINI_API_KEYS_STAGED=` line) |

Phase-A `n_ok` histogram was cleanly bimodal: `{16: 36, ~0: 45}`, nothing between.
The 45 were per-day-exhausted on **both** `gemini-3.5-flash-lite` **and**
`gemini-3.1-flash-lite` after only ~400 cards — impossible for 45 independent
projects (that volume ≈ 50–130 req each; the 500/day cap is only reached if
concentrated into **~4–10 real projects**). The only keys with scraps left sat at
original idx 46/56/66/76 — evenly 10 apart → keys likely minted ~10 per project.

**`.env` now: 69-key working pool** (36 distinct + 33 known-good). Backups in
scratchpad: `.env.backup.full` (119), `.env.backup.pre-deadkey-removal` (119),
`.env.backup.pre-stageout` (114). `.env` is gitignored.

### Job 1 — still open: exact shared-project count + prune to representatives
Phase B (concurrent group bursts to cluster keys by shared per-minute bucket)
**needs per-minute headroom**, which the 45 have on no tested model right now.
Do after Google's RPD reset (~00:00 PT): re-run `key_cluster_probe.py B
--indices <the 45, reindexed>` , get the clusters, keep ~1 key per cluster from
the staged list, delete the rest. Also worth: the owner's `gcloud` path from the
original prompt would give the exact mapping directly and cheaply.

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
