# ADR-0078: Parallelize topics, one key lease each, with a shared reserve

- **Status:** Reverted 2026-09-01 (same day). The code was rolled back to the
  [ADR-0073](0073-worker-runs-generation-jobs-sequentially.md) sequential loop +
  [ADR-0074](0074-key-per-subtopic-scheduling.md) in-topic scheduling that
  [Run 8](../architecture/generation-pipeline-run-8-benchmark.md) proved
  walk-away-safe. **Why:** running many topics at once multiplied per-minute
  pressure on the Gemini free-tier RPM ceilings — with a large key pool, ~40+
  concurrent subtopic-group branches burst the thinking rungs (rpm 5 / rpd 20)
  into sustained 429 storms and per-day exhaustion, and the run stopped being
  something you could start and leave. ADR-0081 was added the same day to patch
  the fresh-topic over-admission hole this opened; it is reverted with this one.
  The follow-on idea worth keeping from here: a **global in-flight LLM-call
  semaphore** sized to real aggregate RPM, so concurrency is a bounded queue
  rather than an unbounded fan-out — see
  [the key-projects handoff](../handoff/next-key-projects-and-experiment-restore.md).
- **Superseded-by (history):** rolled back to ADR-0073 / ADR-0074, then
  reworked as [ADR-0082](0082-fixed-key-boxes-per-topic.md) (2026-09-02), which
  keeps this ADR's goal -- topics in parallel -- and drops the two properties
  that made it unsafe: the box size is a fixed number rather than derived from the
  curriculum's widest tier, and there is no shared reserve to borrow from, so a
  topic's key box is closed.
- **Date:** 2026-09-01
- **Deciders:** Anubhav
- **Amended by:** [ADR-0081](0081-curriculum-as-a-worker-phase.md) -- the worker
  now generates a fresh topic's curriculum in a phase before admission, so
  `topic_tier_width` is real at lease time and the provisional
  `default_topic_key_budget` is a fallback, not the fresh-topic norm.

- **Supersedes:** [ADR-0073](0073-worker-runs-generation-jobs-sequentially.md)'s
  strictly-sequential job loop. The worker runs the admitted jobs concurrently
  again (the pre-ADR-0073 `asyncio.gather` shape), now with a key-budget
  admission step in front of it. ADR-0073's per-job session isolation and
  quota-requeue handling are unchanged.
- **Amends:** [ADR-0074](0074-key-per-subtopic-scheduling.md) -- the unit that
  owns keys is now the TOPIC (a lease of `N` keys), not the subtopic group. A
  group still claims exactly one key for its whole card run, but only from its
  topic's lease; the fallback when that key is spent is the SHARED RESERVE, not
  "any unclaimed key". One caller per key still holds.
- **Amends:** [ADR-0028](0028-key-model-quota-ladder.md) /
  [ADR-0065](0065-quota-governor-fairness-accounting-and-terminal-states.md) --
  the claim-aware ladder's step 2/4 "fallback pool" is the reserve for a leased
  claim; the lease-less path (topic matching, the recovery probe) is byte-for-byte
  ADR-0074's original behaviour.
- **Does not touch:** [ADR-0040](0040-per-cell-call-serialization.md) --
  `cell_lock` still guards the actual send, and is now what makes a per-call
  reserve borrow safe when two branches pick the same reserve key.

## Context

ADR-0074 gave a generation run the whole key pool and made the subtopic group
the unit of key ownership; ADR-0073 then made the worker run one topic at a time,
so a run's demand was one topic's groups. That was the right shape when the pool
was 33 keys and the binding constraint was predictability.

Two things changed. The pool is now **119 keys**
(`core/config.py`'s `GEMINI_KEY_POOL_SIZE`, and `Settings` fails to boot on the
`gemini` backend if `SPOIN_GEMINI_API_KEYS` is not exactly that long -- a short
list is lost capacity that would otherwise read as a quota problem), and the
owner wants throughput: many topics generating at once, not one. Progress *inside* a topic is
difficulty-gated -- a group's tiers are already sequenced lowest-first so a higher
tier builds on the lower one's bodies -- so the parallelism that is actually
available is *across topics*, and across the subtopics of one difficulty tier.
The widest a single topic can ever fan out is therefore the number of subtopics
in its largest difficulty tier: give it that many keys and it can keep all of
them busy on its widest tier, with the narrower tiers leaving some idle.

## Decision

### 1. The worker packs the pending queue by key budget

`run_once()` claims up to `generation_batch_size` pending rows in
`priority DESC, created_at` order, then **admits** them in that order while their
key demand fits the pool:

- A topic's demand `N` is `max` over its difficulty tiers of
  `count(subtopics in that tier)` (`persistence.topic_tier_width`), clamped to
  `[1, pool_size]`.
- A topic with no curriculum yet has no tiers to count, so it gets a provisional
  `settings.default_topic_key_budget` (8). The run recomputes the real `N` once
  `resolve_and_plan_topic` has persisted the curriculum and leases against that.
- Admission adds a job while `sum(N) <= pool_size`, **skips past** one that would
  overflow to try smaller jobs behind it, and leaves the rest `pending` (their
  `FOR UPDATE` lock releases on commit; the next pass re-reads them).
- `pool_size < 1` (the `fake` backend, most tests) means "no packing" -- admit
  everything.
- Repair jobs (ADR-0076) take no lease and always admit, costing 0.

The admitted set runs via `asyncio.gather`, each job on its own session, sharing
one `ContentGenerator` -- so one `KeyClaimRegistry` governs every lease and the
reserve.

### 2. A topic holds a lease of `N` keys for its whole run

`resolve_and_plan_topic` calls `generator.lease_topic_keys(N)`; the lease is
stored on `_Runtime.topic_leases[topic_id]` (a `Send`-spawned branch does not
inherit contextvars, so it cannot ride `CURRENT_KEY_CLAIM`). Every subtopic-group
branch and the topic's question phase claim their one key **from that lease**.
`gate_and_persist` releases each lease once the run's card AND question phases are
done; `run_generation_pipeline`'s `finally` is the crash backstop.

**Which keys a lease takes: coldest first** (ADR-0065's principle, now applied to
leases). A lease is held for a whole run, and a day runs many passes, so
first-fit from key 0 would burn the low indices down pass after pass and leave
the high indices -- and whatever ends up unleased as the reserve -- permanently
cold, with late-day topics leasing already-exhausted cells while budget sits
unused. `GeminiContentGenerator.lease_topic_keys` sums each key's `requests_spent`
across both pools' cells for the day (`quota.key_spend_today`) and hands
`KeyClaimRegistry.lease_topic` a least-spent-first order; the registry follows it
over the leasable keys. Lease growth (`adjust_lease`) does the same. The `fake`
backend has no ledger and leases in index order (it has no keys anyway).

Spare lease keys sit idle while the topic works a tier narrower than `N`. They
are not lent to the reserve -- keeping the lease whole is what lets the next tier
fan out to its full width without re-contending for keys.

If a lease comes back with **zero** keys (the pool was fully leased by concurrent
topics), that topic's branches fall back to the whole-pool scan rather than
deadlocking. The worker's admission step makes this rare; a fresh topic whose
real `N` outran its provisional guess is the case that can still hit it.

### 3. The claim ladder: own key, then the shared reserve

For a subtopic group holding key `X` in lease `L`, thinking pool
`[3.7, 3.6, 3.5, preview]` with `preview` held as the reserve rung:

1. `X` on `3.7`, then `X` on `3.6`.
2. A **reserve key** (in no lease at all) on `3.7`, then on `3.6`,
   least-spent-first. This is a per-call **borrow**: the reserve key serves this
   one call and the claim stays on `X`.
3. `X` on `3.5`.
4. A reserve key on `3.5`.
5. The `preview` rung (own `X`, then reserve) -- ONLY once no key anywhere has
   daily room on an ordinary rung. A spent day, never a busy one.
6. Otherwise wait for a lease key to free (a sibling group finishing) or a window
   to open.

An **unbound** leased claim whose lease is full waits at step 6 rather than
borrowing a reserve key as its home -- the reserve is for a spent key mid-run,
not a first bind. The exception is a genuinely spent day, where step 5 is the
right escalation.

Another topic's leased key is never a fallback, and neither is a sibling group's
key. Two branches borrowing the same reserve key for the same model is possible;
`cell_lock` (ADR-0040) serialises the sends, so they queue rather than 429 --
the same "Harder" note ADR-0074 already accepted for a multi-tier group's gate
fan-out.

The generator pool (no reserve rung, two rungs): own `X` rung 0 -> own `X`
rung 1 -> reserve rung 0 -> reserve rung 1 -> wait.

### 4. The lease-less path is unchanged

`claim=None` -- topic matching from the API process, the recovery probe -- still
gets ADR-0074's original ladder: fallback pool is every unclaimed key, and a
grant there moves the claim. Every test and the `fake` backend take this path.

## Consequences

**Easier**

- Many topics generate per pass instead of one. Throughput scales with the key
  pool, which is now the abundant resource.
- The bound is still one sentence: "each topic holds `N` keys, one caller per
  key, `N` = its widest tier." Concurrency across topics is `sum(N) <= pool`.
- A topic's whole run shows up under a known set of keys in the ledger, so a
  pathological topic is still attributable.
- The reserve gives a topic that burned its strong models a real second model on
  a *fresh* key rather than dropping to `3.5` on a dying one.
- **Per-day usage stays roughly even across the pool.** Cold-first leasing means
  the keys that were reserve (lightly used) on one pass are the ones leased on
  the next, so no key -- and no part of the pool -- is systematically starved or
  systematically hammered over a day of passes.

**Harder**

- **Fresh topics can over-admit.** The worker packs a brand-new topic at the
  provisional budget (8); if its real widest tier is larger, the run leases what
  it can and the shortfall shows up as branches waiting or (worst case) a
  whole-pool fallback. Self-corrects on the next pass once `topic_tier_width`
  returns a real number.
- **Spare lease keys idle.** A topic on a 3-subtopic tier with an 8-key lease
  has 5 keys doing nothing. Deliberate -- lending them out and clawing them back
  per tier is churn, and the reserve already absorbs cross-topic slack.
- **`#groups` can still exceed `N`.** A curriculum where concepts span two or
  three tiers has more groups than its widest tier. Group `N+1` waits for a
  sibling to release a lease key -- a contention wait, seconds, not the RPD wait.
- **A crash after the card phase loses the whole run's question work**, same as
  ADR-0074; `cards_missing_questions` backfills, so it costs a re-run not data.

**Committed to**

- A group never shares a *claimed* key. A reserve *borrow* is per-call and
  `cell_lock`-guarded; it is not a standing share.
- The reserve is keys in no lease, nothing subtler. Not a fraction of each
  lease, not a per-topic quota.
- Unadmitted jobs are left `pending` untouched -- never a partial claim.

## Alternatives considered

**Keep ADR-0073's sequential loop, parallelize only inside one topic.** Simplest,
one `KeyClaimRegistry` with no cross-topic contention. Rejected: it caps
throughput at one topic per pass, and the owner asked for topic-level
parallelism against a pool that can now afford it.

**Bounded topic pool (e.g. 3 topics), ignore per-topic width.** A tuning knob to
justify and re-justify. Rejected for the same reason ADR-0074 rejected a
sub-`K` concurrency cap: "pack by width" needs no number chosen, and a topic's
width is exactly how many keys it can use.

**Lend a topic's idle lease keys to the reserve while it works a narrow tier.**
Higher utilisation. Rejected: the topic then has to re-acquire them (possibly
losing them to another topic) when its next tier needs the width, which is the
churn ADR-0074's whole-run claim exists to avoid. The reserve already soaks up
cross-topic slack.

**Claim a reserve key for the rest of the tier instead of per-call.** Fewer
scans. Rejected: it turns a borrow into a second standing claim, and a topic
whose tier is nearly done would hold a reserve key another topic needs now. Per
the owner's call, the borrow is per-call.

**Cap `N` at `pool_size` and let an oversized topic run alongside others.** Moot
at 119 keys -- no real curriculum has that many subtopics in one tier -- but the
clamp stays as a guard so the packing arithmetic can't wedge.

## Revisit when

- **Fresh topics routinely fall back to the whole-pool scan.** The provisional
  budget is too far from real widths; raise `default_topic_key_budget`, or split
  curriculum into its own worker pass so `N` is always known at admission.
- **`sum(N)` routinely exceeds the pool** and jobs pile up deferred. The pool is
  the constraint again -- more keys first (this scales linearly), then a stated
  over-subscription factor.
- **Reserve borrows collide often enough that `cell_lock` contention shows.**
  Then a borrow should take a short exclusive hold on the reserve key for the
  call, or the "claim reserve for the tier" alternative gets another look.
- **The worker becomes a persistent loop** (ADR-0073's own revisit condition).
  Continuous throughput changes the admission question -- it becomes "keep the
  pool full" rather than "fit this pass".
