# Generation Pipeline Benchmark: Run 5 -- The Quota Ledger Bug, Live

> **Date**: August 26, 2026
> **Scope**: A `QuotaExhaustedError` that disagreed with Google's own dashboard, root-caused
> to two separate bugs in `_classify_rate_limit` and `prune_request_window`, fixed as
> [ADR-0060](../adr/0060-unknown-429-scope-defaults-to-per-minute.md) and
> [ADR-0061](../adr/0061-refund-grants-that-never-became-requests.md), then proven live
> across three sequential topic runs the same day.
> **Status**: Verified Production Proof (Exit Code 0 x3), plus one confirmed operational
> false alarm that was never a code bug at all.

Unlike Runs 1-4 ([`generation-pipeline-test-run.md`](generation-pipeline-test-run.md),
[Run 2](generation-pipeline-run-2-benchmark.md), [Run 3](generation-pipeline-run-3-benchmark.md),
[Run 4](generation-pipeline-run-4-benchmark.md)), this run started as an incident, not a
scaling exercise. It ended up being the best live proof the quota governor has had yet,
specifically because the day also produced a second, unrelated failure that looked
identical on the surface and had to be told apart from the real one.

---

## 1. The bug: a `QuotaExhaustedError` Google's own dashboard contradicted

A generation run for "Mental Models & Cognitive Biases" stopped with:

```
QuotaExhaustedError: All 33 key(s) x 2 model(s) exhausted for 2026-08-26
```

Google AI Studio's live quota page, checked at the same moment, showed 4-87 of 500 spent
per key on the models named. The local ledger and the provider disagreed by roughly an
order of magnitude, and the ledger was wrong.

**Diagnostic signature:** 65 of 66 generator cells sat at *exactly* 500 -- the cap, to the
request -- with `exhausted_at` stamped inside a **100-second window**. Only
`mark_exhausted`'s `requests_spent = max(spent, rpd)` writes exactly `rpd`; organic
consumption does not land 65 independent counters on the same number in 100 seconds. Every
one of those cells had been slammed there from a few dozen real requests.

### Root cause: two defects in `_classify_rate_limit`, same direction

1. **`RetryInfo` was gated behind `not quota_ids`.** A 429 carrying an unrecognized
   `quotaId` alongside a 13-second `retryDelay` skipped the per-minute heuristic entirely
   and fell through to daily. Nothing daily resolves in 13 seconds.
2. **Unknown scope defaulted to `is_daily=True`.** [ADR-0058](../adr/0058-per-minute-vs-per-day-429.md)
   chose that fallback deliberately, on the assumption that a wrong guess costs "one cell
   for a few hours." That assumption didn't hold: `gate_and_persist` fans out across every
   subtopic-tier via `asyncio.gather`, so every in-flight call hits the same RPM ceiling and
   gets misread together. One wrong guess is not one cell -- it's the whole grid, for the
   rest of the day.

**Fix ([ADR-0060](../adr/0060-unknown-429-scope-defaults-to-per-minute.md)):** daily now
requires positive evidence. `RetryInfo` counts on its own regardless of what `quotaId`
accompanies it (and a delay past one RPM window now reads as evidence *for* daily).
Genuinely ambiguous envelopes fall back to per-minute and log the raw payload at WARNING.

### A second, smaller bug found while verifying the first

The ledger also ran ~19% hot on the one cell that survived to compare against the
provider directly (107 local vs 87 real). `acquire()` bills a cell's RPD at grant time, not
send time -- and unlike RPM (which confirms the reservation via `note_request_sent`), RPD
had no equivalent reconciliation. A task that dies between grant and send (a cancelled
`cell_lock` await, `gate_and_persist`'s `asyncio.gather` leaving siblings orphaned when one
raises) leaves a permanent phantom charge.

**Fix ([ADR-0061](../adr/0061-refund-grants-that-never-became-requests.md)):**
`prune_request_window` now reads the `QuotaRequest` rows it drops instead of discarding
them blind. A row still `confirmed=False` five minutes on was never sent (`note_request_sent`
is the first statement in `_invoke_with_backoff`, so a real send confirms within
milliseconds) -- its cell's ledger is credited back. A row that *was* confirmed but got
rejected stays counted, deliberately: the per-minute retry branch depends on the ledger
climbing to terminate, and refunding a 429 would make it retry forever.

### Immediate correction

65 falsely-exhausted cells were reset (`requests_spent = 0, exhausted_at = NULL`) after
confirming each one's provider-side usage was nowhere near its cap. Key 1's genuine partial
spend and the five truly-exhausted `gemini-3.6-flash` cells (20/20, matching the dashboard)
were left untouched.

---

## 2. Live verification

Before the fix, the ledger and the provider had diverged by roughly 30x (32,608 local vs
~1,650 real, from the incident this investigation started with). After the fix, on the very
next run:

| Source | Total requests today |
|---|---:|
| Local ledger (`sum(requests_spent)`) | **1,247** |
| Run's own reported total | **1,246** |

A one-request match. `record_probe_attempt`'s unconditional increment (a background probe
call, not a real generation request) accounts for the difference exactly.

The RPM-cooldown mechanism was also directly visible in the ledger for the first time
without a misfire: nearly every `gemini-3.5-flash` cell sat at `requests_spent = 5`
(that rung's RPM ceiling, not its RPD) with `cooldown_until` set -- `mark_rate_limited`
correctly parking the cell instead of spending it, 75% of that cell's daily budget intact.

---

## 3. Three sequential runs, same day

With the fix live, three topics ran back to back:

| Topic | Cards | Questions | Requests | Duration | Result |
|---|---:|---:|---:|---:|---|
| Rust (Programming Language) | 659 | 647 | 484 | ~20m 17s | Complete, exit 0 |
| Mental Models & Cognitive Biases | 1,307 | 1,301 | 1,756 | ~40m 48s | Complete, exit 0 |
| Financial Literacy & Investing Mechanics | 341 | 340 | 1,246 | -- | Stopped: thinking-pool quota |

Quality gate acceptance across all three sat at 96.3-98.3%, consistent with prior runs.

### The Financial Literacy stop was not the bug this run fixed

Its own pause message read like the incident that opened this document -- "Daily Quality
Gate Quota Limit Hit" -- and it would have been easy to file it under the same root cause.
It wasn't. Every one of the three runs above was preceded by an explicit reset of
`quota_ledger` and `quota_request` to zero, a habit that traced back to a one-time
instruction given to a different agent (Antigravity) the day before, which it then
generalized into doing before every subsequent run without being asked again.

The ledger is deliberately `day`-scoped so it accumulates across every run inside one UTC
day -- that's the entire mechanism that lets a cell already known to be dead get skipped for
free (one local table read) instead of rediscovered the expensive way (a real HTTP
round-trip, which also burns one of `_invoke_with_retry`'s `key_count x len(ladder)`
attempt-budget slots). Zeroing it before Financial Literacy's run meant the pipeline had no
memory of what Rust and Mental Models had already spent on the low-numbered keys that day --
so it re-tried them, ate real 429s re-discovering exhaustion Google already knew about, and
burned through the attempt budget on cells that were never going to work, before ever
reaching keys that still had room.

Read the other way, this is a clean natural experiment: Rust and Mental Models, run without
a stale-ledger handicap immediately behind them, both completed cleanly at high throughput
under the very code this run fixed. Financial Literacy, run identically but with its
memory erased first, is the control that shows what the old bug's failure mode looks like
even after the code is correct -- because this time the cause was procedural, not a defect
to patch.

---

## 4. Live corpus snapshot, `spoin_db` (2026-08-26, post-run)

```
Topic                                                              | Cards | Questions
---------------------------------------------------------------------+-------+----------
Mental Models & Cognitive Biases                                    | 1,307 |    1,301
System Design & Distributed Systems                                 |   756 |      736
Bhagvad Geeta in Easy Language                                      |   753 |      752
German (Language)                                                   |   715 |      687
Kubernetes                                                          |   701 |      687
PostgreSQL                                                          |   696 |      684
How Everyday Things Work                                            |   691 |      691
Rust (Programming Language)                                         |   659 |      647
The Epic of Gilgamesh                                               |   655 |      649
FastAPI                                                              |   625 |      607
Claude Code (Becoming a 10x Developer)                               |   619 |      611
Gym (Physical Fitness)                                               |   613 |      546
10M Air Pistol Shooting                                              |   589 |      581
Building a Successful Kurtis Business in e-commerce for India        |   543 |      503
Study Abroad (Full Guide)                                            |   503 |      497
Current AI Capabilities and Scope                                    |   476 |      475
Financial Literacy & Investing Mechanics                             |   341 |      340
---------------------------------------------------------------------+-------+----------
TOTAL (17 live topics)                                              | 11,242 |   10,994
```

Crossed 11,000 cards for the first time this run, with Mental Models & Cognitive Biases
becoming the largest single topic in the corpus (1,307 cards) in one uninterrupted pass.

---

## 5. Conclusion

The failure this run started from and the failure it ended on wore the same message
("Daily Quality Gate Quota Limit Hit") and pointed at the same subsystem, but were two
unrelated things: one a real defect in how a 429's scope gets read and how a phantom charge
never gets corrected, now fixed and verified to a one-request match against the provider;
the other an external process silently erasing the memory that fix depends on. Telling them
apart mattered -- patching the first bug again would have done nothing for the second, and
assuming the second was a recurrence of the first would have hidden a governor that, by the
end of the day, was working exactly as designed.
