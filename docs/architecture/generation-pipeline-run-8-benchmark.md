# Generation Pipeline Benchmark: Run 8 -- Multi-Topic Marathon & 3.7-First Ladder Verification

> **Date**: August 30, 2026
> **Scope**: Six topics generated to 100% completion plus one topic to 81.2% in a single continuous session under the [ADR-0074](../adr/0074-key-per-subtopic-scheduling.md) key-per-subtopic governor and the restored [gemini-3.7-flash](../adr/0028-key-model-quota-ladder.md) thinking ladder.
> **Status**: Verified Production Proof (6 completed topics, 1 paused at 81.2%, Exit Code 0 across all runs).

Runs 1–6 established the vertical pipeline and baseline throughput (~30–50 min/topic on uncoordinated key selection). Run 7 proved ADR-0074's key-claim architecture on a single topic (CockroachDB in 18m 50s). **Run 8 is the full production stress test**: an unattended multi-topic queue processing **4,139 net new cards** and **1,606 questions** (**5,745 total content items**) in a single day across **33 API keys**.

---

## 1. Summary of Topics Generated Today

Every metric below is extracted directly from the live database (`spoin_db_2`) by `created_at` timestamp bounds for the run window (2026-08-30 09:37 UTC to 12:36 UTC):

| Topic | Subtopics | Cards Today (Total) | Questions Today (Total) | Rejections | Wall-Clock Duration | Avg Speed (Cards/min) | Total Speed (Items/min) | Result |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Linear Algebra** | 33 | 264 (709) | 109 (296) | 3 | 11m 45s | 22.5 | 31.7 | `Exit Code 0` (Completed) |
| **CockroachDB** | 35 | 492 (492) | 292 (292) | 6 | 15m 13s | 32.3 | 51.5 | `Exit Code 0` (Completed) |
| **PostgreSQL** | 45 | 776 (776) | 301 (301) | 21 | 40m 20s | 19.2 | 26.7 | `Exit Code 0` (Completed) |
| **Calculus** | 34 | 743 (743) | 294 (294) | 19 | 23m 42s | 31.4 | 43.8 | `Exit Code 0` (Completed) |
| **Study Abroad (Full Guide)** | 32 | 681 (681) | 309 (309) | 24 | 14m 56s | 45.6 | 66.3 | `Exit Code 0` (Completed) |
| **LangChain** | 36 | 663 (663) | 301 (301) | 24 | 21m 11s | 31.3 | 45.5 | `Exit Code 0` (Completed) |
| **The Epic of Gilgamesh** | 32 | 520 (520) | 0 (0) | 4 | 15m 24s | 33.8 | 33.8 | `Paused` (81.2% cards) |
| **Total (Today's Run)** | **247** | **4,139** | **1,606** | **101** | **~2h 22m active** | **29.1** | **40.4** | **6 completed, 1 paused** |

---

## 2. Live Production Database Metrics (`spoin_db_2`)

Post-Run 8 live snapshot of the production database:

| Metric | Count | Notes |
| :--- | ---: | :--- |
| **Topics** | **73** | Fully formed domain & deep-dive courses |
| **Subtopics** | **714** | Hierarchical concept tiers across beginner, intermediate, advanced |
| **Cards** | **12,785** | Production verified cards with ASCII art, Mermaid diagrams & archetypes |
| **Questions** | **7,508** | Multi-choice and free-text quiz questions |
| **Rejected Cards** | **1,233** | Cumulative lifetime quality-gate rejections |
| **App Users** | **10** | Registered user accounts |
| **Engagement Events** | **935** | User interaction events |

---

## 3. Throughput Speeds: Peak vs Average

### Average Speeds
* **Average Card Generation Rate**: **29.1 cards / minute** (~1,746 cards / hour) across all topics.
* **Average Combined Content Rate**: **40.4 content items (cards + questions) / minute** (~2,424 items / hour).
* **Fastest Single Topic Run**: **Study Abroad (Full Guide)** — **45.6 cards/min** (681 cards in 14m 56s) and **66.3 combined items/min** (990 items in 14m 56s).

### Peak 1-Minute Throughput Bursts
1-minute aggregation buckets across the day captured peak burst rates during concurrent subtopic writes and fan-in question generation:

| Timestamp (UTC) | Peak Throughput | Context |
| :--- | :---: | :--- |
| `2026-08-30 11:41:00` | **309 items / min** | Study Abroad fan-in question phase firing simultaneously across 32 tiers |
| `2026-08-30 10:06:00` | **299 items / min** | CockroachDB fan-in question phase firing across 35 tiers |
| `2026-08-30 10:51:00` | **232 items / min** | PostgreSQL fan-in question phase firing across 45 tiers |
| `2026-08-30 12:04:00` | **223 items / min** | LangChain fan-in question phase firing across 36 tiers |
| `2026-08-30 11:19:00` | **198 items / min** | Calculus fan-in question phase |
| `2026-08-30 11:31:00` | **152 cards / min** | Peak concurrent card drafting burst across 33 subtopic groups |

---

## 4. Quota & Model Tier Performance

Total LLM calls across the day: **4,018 requests**, distributed evenly across all 33 API keys:

```
=== QUOTA USAGE SUMMARY (2026-08-30) ===
Total requests today: 4,018

By Model:
  gemini-3.5-flash-lite : 2,399 requests (Primary drafting ladder)
  gemini-3.6-flash      :   660 requests (Thinking ladder, capped at daily ceiling)
  gemini-3.7-flash      :   608 requests (Restored primary thinking rung)
  gemini-3.5-flash      :   228 requests (Fallback thinking rung)
  gemini-3.1-flash-lite :   123 requests (Fallback drafting rung)
  gemini-3-flash-preview:     0 requests (Emergency reserve unneeded)

Key Distribution (33 active keys):
  81 to 158 requests per key (Mean: ~121.8 requests/key)
```

### Key Discoveries & Fixes Verified
1. **`gemini-3.7-flash` restored and validated**: Verified commit `3351156` resolved the compose env default conflict. Calculus, Study Abroad, LangChain, and Gilgamesh all engaged `gemini-3.7-flash` as the leading thinking rung (608 calls logged).
2. **ADR-0074 Fan-In Question Phase Proven**: Across all 6 completed topics, question generation fired only after all subtopic card bars cleared, completing hundreds of questions within 1–2 minutes at zero competition with card generation keys.
3. **Graceful Throttle Resiliency**: `AllCellsThrottledError` appropriately captured temporary 60-second per-minute rate limit spikes during intense 33-key bursts, safely preserving all state in Postgres and resuming idempotently.
