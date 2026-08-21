# ADR-0047: Removal of Legacy Concurrency Semaphore in Generation Pipeline

## Context

During early development of the generation pipeline ([ADR-0024](0024-langgraph-for-card-generation-pipeline.md), [ADR-0026](0026-one-shot-generation-to-completion.md)), the system did not yet have a multi-key, per-model quota governor. To prevent a single API key from triggering rate limits (429s), an outer global semaphore (`runtime.semaphore = asyncio.Semaphore(settings.max_concurrent_generation_calls)`, default `5`) was wrapped around every generator, gate, and question generation call in `pipeline/nodes.py`.

Later, [ADR-0028](0028-key-model-quota-ladder.md) and [ADR-0040](0040-per-cell-call-serialization.md) introduced a complete, self-contained `QuotaGovernor`:
1. **Per-cell sliding window deques** (`_rpm_has_room`) that enforce exact per-key, per-model RPM ceilings without cross-key interference.
2. **Per-cell call serialization** (`cell_lock`) that serializes concurrent calls to the *same* key while allowing different keys to execute fully concurrently.
3. **Atomic ledger tracking** for daily quotas (RPD) with automatic multi-key fallback.

### The Problem / Testing Impact ("The 40-Key Ferrari in a School Zone")

While the subtopic fan-out in LangGraph was triumphantly made unbounded in Task 0014 / commit `d5bb804`, the forgotten `runtime.semaphore = asyncio.Semaphore(5)` remained quietly standing at the front door like an overzealous bouncer.

During multi-topic production test runs with a massive fleet of 40+ Gemini API keys:
- We built a 40-cylinder Ferrari capable of **>600 Requests Per Minute** with precision per-cell locks, sliding deque windows, and multi-key fallback ladders.
- Yet, this lone semaphore forced the entire 40-key fleet to merge into a single, polite 5-car single-file lane.
- **The Result**: A 3-topic curriculum generation run (176 subtopic tiers, 3,275 production cards, ~3,000 quiz questions) took an agonizing **2.8 hours (~165 minutes)** while developers watched in existential dread as the progress meter hovered at "99.9%" across chained tiers, wondering if the universe itself was rate-limiting them.
- In reality, the keys were essentially on vacation (>90% idle headroom), sipping margaritas while waiting for the semaphore to let 5 requests through at a time.


## Decision

1. **Remove `runtime.semaphore` entirely from `_Runtime`, `graph.py`, and `nodes.py`**:
   - `QuotaGovernor` is now the single source of truth for rate limiting, concurrency, and key rotation.
   - Subtopics and batches dispatch their LLM calls directly to the `QuotaGovernor`.
   - The governor's sliding deque window and per-cell locks safely govern request throughput across all available keys in parallel.

## Consequences

- **True Multi-Key Concurrency**: The pipeline can now utilize all available API keys simultaneously without being throttled by an arbitrary 5-call global ceiling.
- **Drastically Reduced Generation Time**: Multi-topic generation runs with large key pools scale throughput linearly with the number of available keys.
- **Safety Preserved**: Per-key RPM (15 RPM on Flash-Lite, 5 RPM on Flash) remains strictly enforced by `QuotaGovernor._rpm_windows` and `cell_lock`, preventing 429s.
