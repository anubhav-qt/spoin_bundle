# ADR-0083: Load-balance least-spent-first inside a box, and stop shrinking a cell's rpm on a guessed 429

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** Anubhav
- **Mechanism replaced by:** [ADR-0084](0084-per-box-load-balancer.md) -- least-spent-first-per-call and the box/pool split are kept; they are now how `LoadBalancer.try_assign` sorts candidates rather than a `key_scope` argument on `_invoke_with_retry`. The `scope_certain` gate this ADR added is dropped (see ADR-0084 §on learning).

- **Amends:** [ADR-0074](0074-key-per-subtopic-scheduling.md) -- a subtopic
  group's card run no longer PINS to one key. The claim still exists and still
  scopes every scan to the group's box ([ADR-0082](0082-fixed-key-boxes-per-topic.md)),
  but a grant no longer `bind`s it, so each call re-picks the least-spent key in
  the box. ADR-0074's *one-caller-per-cell* guarantee (`cell_lock` +
  `_try_reserve_rpm`) is untouched; what changes is the heuristic layered on top
  of it.
- **Amends:** [ADR-0060](0060-unknown-429-scope-defaults-to-per-minute.md) and
  [ADR-0065](0065-quota-governor-fairness-accounting-and-terminal-states.md)'s
  learned-rpm machinery -- an unidentifiable 429 still parks the cell and
  refunds the day (ADR-0060 is unchanged there), but it no longer also halves
  the cell's learned rpm. The AIMD shrink now fires only when the 429 actually
  identified itself as per-minute.
- **Builds on:** [ADR-0082](0082-fixed-key-boxes-per-topic.md). Boxes bound
  *how many keys* a topic touches; this ADR is about *how a topic spreads its
  calls across the keys it has*. 0082 without this still melted individual keys.

## Context

ADR-0082 landed key boxes: a topic owns a fixed slice of the pool for its whole
run, two topics run at once, and inside a box ADR-0074 was meant to be
unchanged. Benchmarking that against the live pool exposed two defects that
boxes alone did not fix -- both about *per-minute* pressure, which every regime
since ADR-0073 has under-modelled relative to per-day.

### 1. The per-group key PIN concentrates a burst onto one key

ADR-0074 pins a subtopic group to one key for its whole card run: the first
grant `bind`s the claim, and every later call in that group returns that same
key first. The intent was concurrency safety -- one caller per key means no cell
can be raced.

But a subtopic group's "card run" is not a slow trickle. It is a burst: a tier's
plan, then one draft call per card type, then an ASCII fetch and possibly a
redraw -- on the order of ten structured calls in a few seconds, all pinned to
the one key the first call happened to bind. That key's `gemini-3.5-flash-lite`
cell has a 15 rpm ceiling. A single group can trip it by itself, while the
group's *average* call rate over the run stays tiny and 33 other box keys sit
cold. Under ADR-0078 (many wide leases) this compounded into the 429 storms that
got it reverted; under ADR-0082's two boxes it was milder but still there in the
benchmark -- a handful of keys per run doing all the work and periodically
throttling, the rest idle.

The pin was never what made rpm violations impossible. `cell_lock` and
`_try_reserve_rpm`'s atomic reservation do that, per cell, and they are
unchanged. The pin was a *scheduling heuristic* on top -- and it was scheduling
the load into a corner.

### 2. Halving learned rpm on an unidentified 429 walks healthy cells to the floor

ADR-0060 decided that a 429 whose scope cannot be read from the envelope (no
`quotaId`, no short `RetryInfo`) is treated as per-minute: park the cell briefly,
refund the day. ADR-0065's `_shrink_effective_rpm` then also *halves* that cell's
learned rpm on every per-minute 429 -- AIMD, on the theory that the provider
just told us our ceiling estimate was wrong.

Since roughly late August, Google has been returning bare `RESOURCE_EXHAUSTED`
with **no scope information at all** on essentially every 429. So "treat as
per-minute" is now the common path, not the rare fallback -- and the AIMD halving
fires on it every time. Over a multi-hour run a cell that got unlucky a few times
early gets ratcheted 15 -> 7 -> 3 -> 1 and never recovers within the run (the
additive-increase side only nudges it back up slowly on clean calls). The pool's
effective throughput decayed steadily as a run went on, for no measured signal
-- the 429s carried no evidence the real ceiling was any lower than the
configured one.

## Decision

### 1. `key_scope`: three ways to resolve the ambient claim

`_invoke_with_retry` takes `key_scope: Literal["sticky", "box", "pool"]`, and
`GeminiContentGenerator._claim_for_scope` maps it against the contextvar claim
set by `claimed_key_scope`:

| `key_scope` | claim passed to `acquire()` | effect |
|---|---|---|
| `"sticky"` | the ambient claim as-is (or `None`) | ADR-0074's pin. Also the no-claim callers -- curriculum, topic matching, name validation, grading -- which just get the whole pool. |
| `"box"` | a fresh `KeyClaim(box=<ambient box>, sticky=False)` | scoped to the topic's box, but **no pin**: this call picks the least-spent key in the box, the next call re-picks. |
| `"pool"` | `None` | least-spent over the whole pool, no box, no pin. |

`KeyClaim` gains `sticky: bool = True`. When `False`, a grant never calls
`claims.bind()`, so `key_index` stays `None` and every call re-runs the
least-spent scan. `cell_lock` still serialises the send, so "no pin" does not
mean "two callers on a cell" -- it means the *choice* of cell is made fresh each
call instead of frozen at the first.

**What runs where:**

- **`"box"`** -- card planning, card writing, ASCII fetch, ASCII redraw,
  question generation, repair. A unit's burst spreads least-spent-first across
  its ~34 box keys instead of hammering one.
- **`"pool"`** -- the thinking gate (`correct_cards`, `verify_cards`). Its rungs
  are rpm 5 / rpd 20 -- the tightest in the ladder -- so its calls must spread
  the widest. Pool-wide, because gate work for one topic is not more entitled to
  a box key than the box's own card writing.
- **`"sticky"`** -- the default, for callers with no ambient claim. Unchanged.

This is, deliberately, the **pre-ADR-0074 / ADR-0065 least-spent-first
behaviour**, now scoped by ADR-0082's box rather than run pool-wide.

### 2. `scope_certain` / `shrink_rpm`: the AIMD shrink needs real evidence

`_RateLimit` gains `scope_certain: bool = True`. `_classify_rate_limit` sets it
`False` on the path where neither a `quotaId` nor a short `RetryInfo` was present
and per-minute is only the safe *guess*. `_invoke_with_retry` passes
`shrink_rpm=limit.scope_certain` into `mark_rate_limited`, and
`_mark_rate_limited_with_session` calls `_shrink_effective_rpm` only when
`shrink_rpm` is set.

A guessed per-minute 429 still does everything else it did: the cell is parked
for the cooldown, the day is refunded, the retry loop still terminates on a
measured throttle streak (`_invoke_with_retry`). It just no longer ratchets the
learned ceiling down on a 429 that carried no information about where the
ceiling is.

An identified per-minute 429 (`quotaId` present, or a short `RetryInfo`) is real
evidence and still shrinks the cell, exactly as ADR-0065 wrote it.

## Consequences

**Easier**

- **A topic's burst spreads across its whole box.** No single key does a run's
  worth of card writing; the throttle rate in a boxed benchmark drops toward the
  Run 8 baseline.
- **Learned rpm stops decaying on noise.** A cell's ceiling only moves down when
  the provider actually said per-minute. Pool throughput no longer sags over a
  long run.
- **One mechanism, one contextvar.** `key_scope` is resolved in one place from
  the same claim `claimed_key_scope` already sets; nodes pass a string.

**Harder**

- **The "one key per subtopic group" mental model is gone.** ADR-0074's headline
  is now "one key per *cell* per call" -- the box is the unit that stays stable
  for a run, not the key. Anyone reading ADR-0074 needs this ADR and ADR-0082
  next to it.
- **`sticky` is a second axis on `KeyClaim`.** A claim now has box scope and pin
  independently; `sticky=True, box=None` (the ADR-0074 default) and
  `sticky=False, box=<b>` (generation) are the two live combinations, and the
  other two are legal but unused.
- **A genuinely lower real ceiling is now learned more slowly.** If a cell's
  true rpm really is below the configured one and the provider keeps refusing to
  say so, we find out by the throttle-streak terminating the retry loop rather
  than by the ceiling adapting. That is the right trade while every 429 is
  scopeless, and it is the thing to undo first if the provider starts labelling
  them again.

**Committed to**

- **The pin is off for generation and stays off** unless a benchmark shows
  spreading is worse than concentrating (it will not -- concentration was the
  problem).
- **`cell_lock` + `_try_reserve_rpm` remain the only thing between a cell and an
  rpm violation.** Nothing in this ADR weakens that; it removes a heuristic that
  was sitting on top of it and mis-scheduling.

## Alternatives considered

**Keep the pin, shrink the box further.** Fewer box keys per topic would force
some spread. Rejected: it does not spread a *group's* burst -- that still lands
on one key -- it just makes the box tighter for every other reason too. The pin
is the thing concentrating the load; shrink the box and the pin still corners it.

**A global in-flight LLM-call semaphore sized to real aggregate rpm.** The idea
the ADR-0078 revert note left behind, and still the right long-term shape if
per-minute pressure keeps binding. Not done here because least-spent-first
spreading is a one-scan change that gets most of the benefit; the semaphore is
the next lever if boxes + spreading still throttle above baseline (also
ADR-0082's first revisit trigger).

**Stop treating unidentified 429s as per-minute at all** (re-open ADR-0060).
Rejected: ADR-0060's core call is still right -- an unidentified 429 with the
day's ledger showing budget is far more likely a throttle than a real
exhaustion, and treating it as exhaustion is what stopped whole runs early. Only
the *rpm ratchet* on that guess was wrong, and that is all this ADR removes.

**Halve rpm but recover it faster on clean calls.** Tune the additive-increase
side of the AIMD instead of gating the multiplicative-decrease. Rejected: it
still pays the decay every time on the common path and hopes to climb back; the
signal was never there to justify the first halving.

## Revisit when

- **A boxed benchmark still shows 429 rates above Run 8's** even with spreading.
  Then per-minute pressure is binding independently of how load is scheduled,
  and the global rpm semaphore is the next move (shared with ADR-0082's revisit).
- **Google starts returning scoped 429s again** (`quotaId` populated on
  `RESOURCE_EXHAUSTED`). Then `scope_certain` is `True` on that path by
  construction and the AIMD shrink resumes with no code change -- worth
  confirming the learned rpm is actually adapting again rather than pinned at the
  configured ceiling.
- **A run shows a cell stuck at a low learned rpm with no matching per-minute
  429s in the log.** The shrink is firing on a path that should be
  `scope_certain=False`; check `_classify_rate_limit`'s branches against a real
  envelope sample.
- **`sticky=True` acquires a box key anywhere in the generation path.** Some
  caller is still pinning; it should be `key_scope="box"` or `"pool"`.
