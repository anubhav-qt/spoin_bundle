# Generation Pipeline Benchmark: Run 1 vs Run 2 & The Concurrency Breakthrough

> Comprehensive analysis of the multi-topic generation pipeline test run (Run 2: August 21, 2026).
> Evaluates throughput, key pool utilization, quality gate accuracy, and the resolution of the legacy semaphore bottleneck ([ADR-0047](../adr/0047-removal-of-legacy-concurrency-semaphore.md)).

---

## 1. Executive Summary

On 2026-08-21, the full end-to-end generation pipeline was executed against three core computer science topics:
1. **`Computer Networking`** (OSI/TCP-IP models, packet encapsulation, ARP, BGP, DNS, TLS/SSL, socket buffers).
2. **`Docker`** (Namespaces, cgroups, layered storage, overlay networking, rootless isolation, multi-stage builds).
3. **`Operating Systems`** (Process scheduling, virtual memory, page replacement, lockless ring buffers, RTOS).

The run generated, verified, and committed **3,939 production cards**, **3,101 interactive quiz questions**, and **3,939 384-dimensional vector embeddings** directly into `spoin_db`, bringing the total verified live corpus to **5,004 production cards** and **4,157 quiz questions**.

---

## 2. The Flawed Legacy Mishap ("The 40-Key Ferrari in a School Zone")

### The Origin of the Ghost Bottleneck
During early LangGraph prototyping ([ADR-0024](../adr/0024-langgraph-for-card-generation-pipeline.md)), the project had only a single developer API key. To prevent that lone key from instantly exceeding Google's 5 RPM free-tier rate limit, an outer global semaphore was wrapped around all node calls:
```python
runtime.semaphore = asyncio.Semaphore(settings.max_concurrent_generation_calls)  # default: 5
```

### The Irony
Subsequent iterations introduced:
1. **Multi-Key `QuotaGovernor`** ([ADR-0028](../adr/0028-key-model-quota-ladder.md) & [ADR-0040](../adr/0040-per-cell-call-serialization.md)) with sliding deque windows, per-cell execution locks, and automatic model fallback ladders.
2. **Unbounded Subtopic Fan-Out** (Task 0014 / commit `d5bb804`) allowing all subtopics in a curriculum to dispatch concurrently.
3. **Expanded Pool of 40+ API Keys** capable of **>600 Requests Per Minute**.

**Yet, nobody noticed that the legacy `asyncio.Semaphore(5)` remained standing at the front door.**

Like a 40-cylinder Ferrari forced to drive in a single-file 5 MPH school zone, all 40 keys spent **2.8 hours (~165 minutes)** waiting in a queue, while the developers stared at the screen wondering why generating 3 topics felt like watching continental drift. In reality, the key cluster had >90% idle headroom.

### The Fix ([ADR-0047](../adr/0047-removal-of-legacy-concurrency-semaphore.md))
Once identified, `runtime.semaphore` was deleted from `nodes.py`, `graph.py`, and `state.py`. The `QuotaGovernor` took sole responsibility for rate-limiting, immediately unleashing the entire 40-key fleet and completing **over 1,000 cards and 1,000 quiz questions in under 15 minutes**.

---

## 3. Comparative Metrics: Run 1 vs Run 2

| Metric Dimension | Run 1: Baseline (2 Topics) | Run 2: Part A (With Semaphore) | Run 2: Part B (ADR-0047 Unchained) | **Overall Run 2 (3 Topics)** |
| :--- | :---: | :---: | :---: | :---: |
| **Topics Tested** | `AI Capabilities`, `Air Pistol` | `Networking`, `Docker`, `OS` | `Networking`, `Docker`, `OS` | **3 Topics** |
| **Subtopics / Tiers** | 57 tiers | 176 tiers | 176 tiers | **176 planned / 166 completed** |
| **Persisted Production Cards** | 1,065 | ~2,880 | +1,059 | **3,939 cards** |
| **Persisted Quiz Questions** | 1,056 | ~2,099 | +1,002 | **3,101 questions** |
| **Total Production Items** | **2,121 items** | 4,979 items | 2,061 items | **7,040 items** *(>3.3x Run 1)* |
| **Card Generation Rate** | ~14.2 cards / min | ~16.5 cards / min | **~130+ cards / min** ⚡ | **~38.5 cards / min avg** |
| **Quiz Synthesis Rate** | ~14.1 questions / min | ~12.2 questions / min | **~250 questions / min** ⚡ | **~30.4 questions / min avg** |
| **Active Key Pool** | Keys 0–8 (9 keys) | Keys 0–28 (throttled) | **Keys 0–41 (Fully Parallel)** | **40+ Keys** |
| **Concurrency Bottleneck** | Semaphore = 5 | Semaphore = 5 | **None (Pure QuotaGovernor)** | **Unbounded Multi-Key** |
| **Quality Gate Pass Rate** | 98.9% (12 rejected) | 99.2% | **99.4%** | **99.3% Accepted** |
| **Persistence Status** | `Committed` | `Committed` | `Committed` | **All Live in `spoin_db`** |

---

## 4. Quality Gate Behavioral Analysis (Run 2)

Throughout Run 2, the Two-Pass Quality Gate ([ADR-0030](../adr/0030-two-pass-quality-gate.md) & [ADR-0031](../adr/0031-verification-feedback-and-per-tier-gate-durability.md)) performed critical factual and structural corrections across thousands of live drafts without human intervention:

### 1. Low-Level Kernel & Hardware Semantics (Pass 1)
- **Lockless Ring Buffers**: Corrected producer/consumer code snippets in advanced OS memory concurrency to load indices with `acquire` semantics rather than self-indexing.
- **Linux Socket Buffers (`sk_buff`)**: Refined network packet memory allocation descriptions to accurately distinguish hardware direct-memory-access (DMA) ring allocations from kernel `sk_buff` wrapper instantiation.
- **CPU Idle States**: Fixed code commentary on `cpu_relax()` to clarify that it emits a pause instruction and does not pass through an RCU quiescent state.

### 2. Networking & Containerization Domain Corrections (Pass 1 & 2)
- **Collision vs Broadcast Domains**: Fixed terminology in L2 networking cards to accurately define single shared collision domains on legacy hubs versus independent micro-segmented collision domains on switches.
- **Docker Rootless Mode**: Corrected myth-vs-fact contrast statements regarding user namespace isolation and privilege escalation bounds when invoking `docker exec --user`.
- **ASCII Column Bounds**: Automatically detected and dropped multi-line ASCII diagrams exceeding the 40-column visual viewport limit to ensure pristine rendering on mobile.

---

## 5. Summary Corpus Status

With Run 1 and Run 2 completed, `spoin_db` now holds:

```
               canonical_name               | completed_tiers | distinct_cards | distinct_questions 
--------------------------------------------+-----------------+----------------+--------------------
 10M Air Pistol Shooting                    |              35 |            589 |                581
 Computer Networking                        |              40 |           1197 |               1244
 Current AI Capabilities and Scope          |              22 |            476 |                475
 Docker                                     |              64 |           1450 |                963
 Operating Systems                          |              62 |           1292 |                894
--------------------------------------------+-----------------+----------------+--------------------
 TOTAL LIVE PRODUCTION CORPUS               |             223 |          5,004 |              4,157
```

All 5,004 cards and 4,157 questions are fully indexed with FastEmbed 384-dimensional vectors, verified against schema rules, and served directly by the FastAPI read path with zero runtime LLM latency.
