# Task 0037: Reconcile the token estimate against real `usageMetadata`

**Status:** Open
**Raised by:** [ADR-0085](../adr/0085-tokens-are-metered-too.md), 2026-09-03

## What

The balancer's per-cell trailing-minute token window (ADR-0085) is fed by an
ESTIMATE: `estimate_tokens(text) = len(text) // 4`, in
`apps/api/src/spoin/generation/load_balancer.py`. Replace it — or rather,
correct it after the fact — with the real token count the provider reports.

## Why it wasn't done in ADR-0085

The exact count lives in the response's `usageMetadata`. Our calls go through
`structured = client.with_structured_output(schema)` and then
`structured.ainvoke(prompt)`, which returns the **parsed pydantic model**, not
the `AIMessage` that carries `usage_metadata`. Getting at it needs
`with_structured_output(schema, include_raw=True)`, which changes the return
shape to `{"raw": AIMessage, "parsed": Model, "parsing_error": ...}` at every
call site in `langchain_impl.py`. That is a wide, mechanical refactor and it did
not belong inside a fix for a live generation outage.

## Shape of the work

1. Switch `_invoke_with_backoff` to `include_raw=True` and unwrap `parsed`
   centrally, so call sites keep their current return types.
2. Add `LoadBalancer.on_usage(res, *, tokens, now)` that replaces the estimated
   entry in `cell.token_window` with the reported total, keyed on the slot's
   `sent_at` (the same trick `on_send_aborted` uses).
3. Log estimate vs actual for a run, then decide whether `// 4` needs a
   per-model coefficient. Prompts here are heavy on ASCII art and JSON, neither
   of which tokenizes like English prose — the estimate may be systematically
   off in one direction.

## Done when

The window is fed by reported usage, and a run's estimate-vs-actual spread is
recorded in the ADR-0085 revisit notes.
