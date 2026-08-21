# Task 0014: Remove artificial drafting round constraints and allow unbounded completion

**Owner:** unassigned

## The problem

In `src/spoin/generation/pipeline/nodes.py`, the card drafting loop calculates an artificial round ceiling:

```python
max_rounds = max(
    len(all_card_types) * 2, math.ceil(target / batch_size) + len(all_card_types)
)
for round_number in range(1, max_rounds + 1):
    remaining = target - len(drafts)
    if remaining <= 0:
        break
```

This ceiling was originally introduced as a defensive guard when key rate limits could stall loops and when generation pipeline errors needed early visibility.

## Why it matters

With per-group atomic persistence (ADR-0041), multi-key rotation, and thinking/generator fallback ladders (ADR-0028) now fully operational, rate-limit failures and lost progress risks are solved. Artificial round caps can prematurely terminate a subtopic's card drafting if individual batch calls return fewer items than expected.

## What to do

1. Update `nodes.py` to allow unbounded drafting until `remaining <= 0` (or purely progress-driven termination `if not result.items and ...`).
2. Retain the two-pass quality gate (ADR-0030) and per-group persistence (ADR-0041) intact.
3. Verify via `test_generation_pipeline.py` and `test_langchain_impl.py`.

## Timebox

Small -- a clean refactor in `nodes.py` (15-30 minutes).
