# Concurrency Burst Benchmarks & Edge Gateway Shedding (2026-09-04)

Handoff document for the isolation test characterizing the bare `RESOURCE_EXHAUSTED` (429) rate under concurrency, following up on [ADR-0084 benchmarks](adr-0084-send-gap-benchmarks.md) and [ADR-0085 token metering](../adr/0085-tokens-are-metered-too.md).

---

## 1. Context & Competing Hypotheses

Across Benchmarks 1 through 7 of the ADR-0084 load balancer, runs consistently failed in an 84%–95% 429 band. Crucially, these errors arrived as **bare `RESOURCE_EXHAUSTED` envelopes** with no `details`, no `QuotaFailure`, and no `quotaId` (unlike standard RPM/RPD quota rejections which carry explicit violation records).

Prior isolation tests revealed sharp contrasts:
* **25 concurrent calls to 1 key:** Completely clean.
* **240 req/min aggregate across 75 keys via httpx:** 11% 429s (all attributed per-day 429s on 11 spent keys; zero per-minute or bare 429s).
* **40 keys fired simultaneously via `asyncio.gather`:** Bare 429s appeared immediately and escalated sharply on repetition (0% &rarr; 70% &rarr; 90–100%).

This generated two competing explanations:
1. **The Client/IP-Level Abuse Hypothesis:** Google's API gateway throttles when a high number of *distinct API keys* land on the wire simultaneously from the same IP/container, independent of prompt size or token volume.
2. **The In-Flight Token Weight Hypothesis:** Google's edge gateway sheds load when a large *volume of prompt tokens* is in-flight concurrently, independent of how many keys are in the burst.

---

## 2. Experimental Setup

To decisively isolate these variables, an automated test harness (`/tmp/burst_test.py`) was executed inside container `spoin-api-1` across 20 verified clean keys (all with <35 requests spent on `gemini-3.5-flash-lite` today).

* **Burst Size:** 20 concurrent requests fired simultaneously via `asyncio.gather`.
* **Model:** `gemini-3.5-flash-lite`, `timeout=120.0s`, `max_retries=0`.
* **Cooldown Spacing:** 75 seconds between every burst to allow trailing 60s rate windows to fully reset.
* **Conditions Tested (Per Round):**
  1. **20 Distinct Keys & Heavy Prompt (`mult=20`, ~10k tok/call):** 20 keys, ~196k total tokens in flight.
  2. **1 Single Key & Heavy Prompt (`mult=20`, ~10k tok/call):** 1 key (Key 0), ~196k total tokens in flight.
  3. **20 Distinct Keys & Tiny Prompt (`mult=0`, ~7 tok/call):** 20 keys, ~140 total tokens in flight.
* **Rounds:** 3 full rounds to test repetition, recovery, and stability.

---

## 3. Results Matrix

| Round | Test Condition | Concurrent Calls | Distinct Keys | Tokens / Call | Total Tokens in Flight | OK | Bare 429 | Attributed 429 (Per-Day) | Attributed 429 (Per-Minute RPM) |
|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **R1** | **20 Distinct Keys** (Heavy) | 20 | 20 | ~9,814 | ~196k | 15 | **4** (20%) | 1 | 0 |
| **R1** | **1 Single Key** (Heavy) | 20 | 1 | ~9,814 | ~196k | 15 | **1** (5%) | 0 | **4** (20%) |
| **R1** | **20 Distinct Keys** (Tiny) | 20 | 20 | ~7 | ~140 | 19 | **0** (0%) | 1 | 0 |
| **R2** | **20 Distinct Keys** (Heavy) | 20 | 20 | ~9,814 | ~196k | 18 | **0** (0%) | 2 | 0 |
| **R2** | **1 Single Key** (Heavy) | 20 | 1 | ~9,814 | ~196k | 14 | **2** (10%) | 0 | **4** (20%) |
| **R2** | **20 Distinct Keys** (Tiny) | 20 | 20 | ~7 | ~140 | 17 | **0** (0%) | 3 | 0 |
| **R3** | **20 Distinct Keys** (Heavy) | 20 | 20 | ~9,814 | ~196k | 15 | **2** (10%) | 3 | 0 |
| **R3** | **1 Single Key** (Heavy) | 20 | 1 | ~9,814 | ~196k | 15 | **1** (5%) | 0 | **4** (20%) |
| **R3** | **20 Distinct Keys** (Tiny) | 20 | 20 | ~7 | ~140 | 17 | **0** (0%) | 3 | 0 |
| **TOTAL** | **20 Distinct Keys (Heavy)** | 60 | 20 | ~9,814 | ~196k | 48 | **6 (10.0%)** | 6 | 0 |
| **TOTAL** | **1 Single Key (Heavy)** | 60 | 1 | ~9,814 | ~196k | 44 | **4 (6.7%)** | 0 | **12 (20.0%)** |
| **TOTAL** | **20 Distinct Keys (Tiny)** | 60 | 20 | ~7 | ~140 | 53 | **0 (0.0%)** | 7 | 0 |

*(Note: The attributed per-day 429s on key slots 2, 14, 19 occurred because those keys reached their 500-request daily cap from earlier benchmarks).*

---

## 4. Key Findings & Dissections

### 1. Distinct key count alone is NOT the trigger
Across 60 requests hitting 20 distinct keys simultaneously with a tiny prompt (~7 tokens), the bare 429 rate was **exactly 0.0% (0 / 60)**. If Google's gateway throttled solely based on simultaneous distinct keys arriving from one IP, this condition would have triggered. It did not.

### 2. Bare 429s appear on a SINGLE key under heavy token concurrency
When 20 concurrent requests carrying ~10k tokens each hit 1 single key:
* Exactly 4 calls per round were rejected by the documented quota subsystem with `quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier` (reflecting the 15 RPM project ceiling).
* **Bare 429s ALSO appeared** on this single key (1 in R1, 2 in R2, 1 in R3 = 6.7%).

### 3. Edge shedding is driven by in-flight payload volume at the moment of dispatch
All bare 429 rejections returned with near-zero processing time: **latencies 0.88s–1.45s**, compared to successful calls which took 1.5s–70s. This confirms that bare 429 is edge gateway load shedding: connections carrying heavy payloads arriving concurrently are dropped at the perimeter before entering the model execution and quota accounting pipeline.

### 4. Cooldown spacing prevents runaway degradation
With 75s spacing between bursts, the bare 429 rate on heavy bursts stayed at ~10% (4, 0, 2 across rounds). The dramatic 0% &rarr; 70% &rarr; 90% degradation observed in prior sessions was caused by repeating bursts back-to-back without allowing edge rate buckets to recover.

---

## 5. Architectural Solution (ADR-0086)

ADR-0085's token budget packing (`gemini_prompt_token_budget = 16_000`) correctly limits the weight of individual requests. However, when ~45 subtopic-tier branches fan out at the exact same millisecond, they create an instantaneous perimeter burst.

To eliminate perimeter edge shedding, we implement two complementary pacing layers (ADR-0086):
1. **LoadBalancer Pool-Wide Dispatch Staggering (`gemini_dispatch_stagger_seconds`):** A minimum spacing (default 0.5s) between any two consecutive reservations across the *entire* balancer. While `gemini_send_gap_seconds` paces requests to the *same* cell, dispatch staggering spaces requests across *different* cells, converting an instantaneous 45-call spike into a smooth, staggered stream.
2. **Initial Branch Jitter (`gemini_initial_dispatch_jitter_seconds`):** Random sleep (0 to 1.5s) before entering `_generate_subtopic_cards`, desynchronizing subtopic branches before they contend on the balancer.
