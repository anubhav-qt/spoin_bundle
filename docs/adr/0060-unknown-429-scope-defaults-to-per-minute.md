# ADR-0060: An unidentifiable 429 is a throttle, not an exhaustion

- **Status:** Accepted (amends [ADR-0058](0058-per-minute-vs-per-day-429.md))
- **Date:** 2026-08-26
- **Deciders:** Anubhav
- **Amended by:** [ADR-0083](0083-least-spent-load-balancing-within-a-box.md) --
  an unidentifiable 429 is still treated as per-minute (parked, day refunded;
  this ADR's call, unchanged), but it no longer *also* halves the cell's learned
  rpm. Google now returns scopeless `RESOURCE_EXHAUSTED` on nearly every 429, so
  the AIMD shrink was firing on the common path and walking healthy cells to the
  1-rpm floor. The shrink now needs a `quotaId` or a short `RetryInfo` --
  `_RateLimit.scope_certain`.

## Context

[ADR-0058](0058-per-minute-vs-per-day-429.md) taught the generator to read a 429's
`quotaId` and tell a per-minute throttle from a per-day exhaustion. That part works and is
unchanged. What this ADR reverses is the *fallback* it chose for a 429 whose scope cannot be
identified: daily.

On 2026-08-26 a run stopped with the familiar-looking message:

```
QuotaExhaustedError: All 33 key(s) x 2 model(s) exhausted for 2026-08-26
```

The provider's own dashboard, read live at that moment, disagreed flatly:

| Model | Our ledger | Google's dashboard |
|---|---|---|
| `gemini-3.5-flash-lite` | 500 / 500 | 37, 58, 87 / 500 |
| `gemini-3.1-flash-lite` | 500 / 500 | 9, 4, 6 / 500 |
| `gemini-3.6-flash` | 20 / 20 | 20 / 20 (genuinely spent) |

The ledger told the shape of the failure precisely. 65 of the 66 generator cells sat at
*exactly* 500 — the cap, to the request — with `exhausted_at` stamped inside a **100-second
window** (10:34:44 → 10:36:21). One straggler sat at 107, un-exhausted. Organic consumption
does not land 65 independent counters on precisely the same number within 100 seconds;
`mark_exhausted`'s `requests_spent = max(requests_spent, rung.rpd)` is the only code path
that writes exactly `rpd`. Every one of those cells had been *slammed* from a few dozen real
requests to its cap.

The dashboard also showed the trigger, in the adjacent column: RPM at 14/15, 12/15, and
**16/15** — the per-minute ceiling saturated and briefly exceeded. So the pipeline was
generating a flood of per-minute 429s, and each one was being read as a day-long exhaustion.

Two defects in `_classify_rate_limit`, pointing the same way:

1. **`RetryInfo` was consulted only when no `quotaId` was present at all** (`if not
   quota_ids and retry_after is not None ...`). A 429 carrying an unrecognized quota id
   *alongside* a 13-second `retryDelay` skipped the heuristic entirely and fell through to
   daily. Nothing daily resolves in 13 seconds; the delay was sitting right there in the
   payload, being discarded because of what accompanied it.
2. **The final fallback was `is_daily=True`.**

ADR-0058 chose that fallback deliberately and named the trade: "a per-minute limit misread
as daily costs one cell for a few hours, while a daily exhaustion misread as per-minute
would retry a genuinely dead cell hundreds of times." It even listed the exact alternative
this ADR now adopts, and rejected it.

**The asymmetry it assumed is not the one that exists.** That reasoning treats
classification errors as *independent* — one bad guess, one cell. They are **correlated**.
`gate_and_persist` fans out across every subtopic-tier at once via `asyncio.gather`
(`pipeline/nodes.py`), so every in-flight call crowds the same per-minute ceiling and gets
throttled within seconds of every other. One wrong guess is not one cell for a few hours; it
is the entire grid for the rest of the day. That is the measurement above.

ADR-0058 predicted this failure in its own "Harder" section — "If they stop [populating
`quotaId`], every 429 lands in the unknown-scope fallback and behaviour reverts to today's
(over-eager exhaustion), which is the safe direction but is the bug we just fixed" — and
listed the signal in "Revisit when". This is that condition firing. Reversing the fallback
is what the earlier ADR asked a later one to do, not a re-litigation of it.

## Decision

**Daily requires positive evidence. Ambiguity is treated as a per-minute throttle.**

`_classify_rate_limit` now resolves, in order:

| Signal | Verdict |
|---|---|
| `quotaId` contains `PerDay` | daily |
| `quotaId` contains `PerMinute` | per-minute, honouring `RetryInfo` |
| `RetryInfo` ≤ one RPM window | per-minute — **regardless of what `quotaId` accompanies it** |
| `RetryInfo` > one RPM window | daily — a delay past a minute cannot describe a per-minute limit |
| neither signal | **per-minute**, logged at WARNING with the raw envelope |

Two changes from ADR-0058: `RetryInfo` is now evidence in its own right rather than only
when no `quotaId` was sent (closing defect 1, and newly reading a *long* delay as positive
evidence *for* daily), and the terminal fallback flips (defect 2).

**The unknown case is logged, not silently guessed.** The envelope shape is the only way a
later session learns which quota ids this parser still doesn't recognize — and given this is
the second time a 429-classification bug has masqueraded as a content or capacity problem,
the raw payload belongs in the log rather than in the next investigation's guesswork.

## Consequences

**Easier.** A throttle can no longer cost a day. The worst case for an unidentifiable 429 is
now a 60-second park on one cell, against a grid of 66 — recoverable by construction, where
the old worst case was terminal until midnight UTC. `quota_ledger.requests_spent` stays a
believable number instead of a wall of identical caps, which matters because it is the
figure any "how much is left?" question gets answered from. And an unrecognized envelope now
announces itself in the logs instead of quietly taking the destructive branch.

**Harder.** A genuinely per-day 429 that carries *neither* a `PerDay` quota id *nor* a
`RetryInfo` will now be retried rather than retiring its cell. This is the cost ADR-0058
named, and it is real but bounded three ways: the cell is parked 60s per attempt, retries
interleave across the whole grid rather than hammering one key, and `acquire()`'s monotonic
increment walks the cell toward its own RPD ceiling until it retires itself — the argument
`_invoke_with_retry`'s docstring already makes for known per-minute 429s. The new
long-`RetryInfo` rule also catches any such 429 that carries a delay at all.

**Unchanged, and still worth knowing.** Per-minute retries still consume real RPD in our
ledger, since `acquire()` increments before the call and a *rejected* request does not count
against the provider's daily total. Measured on the surviving un-slammed cell: ledger 107 vs
Google's 87 — roughly 20% over-count under heavy throttling. That drift is in the safe
direction (we under-use rather than over-run) and is deliberately left alone here; it is a
separate concern from which branch an ambiguous 429 takes.

## Alternatives considered

**Keep the daily fallback and just fix the `RetryInfo` gating (defect 1 only).** Tempting,
since defect 1 alone plausibly explains the observed cascade — the captured envelopes do
carry a `RetryInfo`. Rejected because it leaves the grid one undocumented envelope change
away from the identical day-long outage, and `quotaId` stability is precisely the dependency
ADR-0058 flagged as its own biggest risk. Fixing only the symptom we happened to catch
preserves the failure mode.

**Track consecutive unknown-429s per cell and escalate to daily after N.** Splits the
difference and would bound the dead-key retry cost precisely. Rejected: it invents a tuning
constant to paper over missing information, adds per-cell state to a governor whose
correctness already depends on subtle cross-process reasoning, and the mechanism it
duplicates — a cell walking to its own RPD ceiling and retiring — already exists.

**Trust the provider's `RetryInfo` exclusively and drop `quotaId` parsing.** Simpler, and
`RetryInfo` proved the more reliable field here. Rejected for ADR-0058's original reason: it
is an inference where the payload offers a direct statement, and a per-day 429 carrying a
short delay would be retried all day.

## Revisit when

- The new WARNING (`a 429 arrived with no recognizable scope`) starts appearing in volume —
  the envelope shape has moved again, and the quota-id table needs updating rather than the
  fallback being leaned on.
- `quota_ledger` shows cells retiring at their exact `rpd` in tight clusters again. That
  signature is what identified this bug and would identify its recurrence.
- ~~The ledger's over-count under sustained throttling (see "Unchanged", above) starts
  costing meaningful daily headroom — that is the point to make RPD confirm-on-send the way
  ADR-0058 made RPM, rather than charging it at grant time.~~ **Acted on the same day by
  [ADR-0061](0061-refund-grants-that-never-became-requests.md)**, which found the drift is
  two separate facts: a grant that never became a request is now refunded, while a rejected
  send stays counted because this ADR's own per-minute branch depends on the ledger climbing
  to terminate.
- A paid tier lands: per-minute limits scale differently, and the hand-copied RPD/RPM
  figures ([ADR-0028](0028-key-model-quota-ladder.md)) need rechecking regardless.
