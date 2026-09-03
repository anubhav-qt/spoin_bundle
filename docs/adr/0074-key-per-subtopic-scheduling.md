# ADR-0074: One key per subtopic group, and questions after the topic's cards

- **Status:** Accepted
- **Date:** 2026-08-30
- **Deciders:** Anubhav
- **Superseded by:** [ADR-0084](0084-per-box-load-balancer.md) -- the `KeyClaim` / `KeyClaimRegistry` classes are deleted. A box is now a `LoadBalancer` over a fixed key slice; there is no per-group claim or pin (ADR-0083 had already retired the pin). "One key per subtopic group" is not how it works any more; one caller per `(key, model)` cell per call is.
- **Amended by:** [ADR-0082](0082-fixed-key-boxes-per-topic.md) -- "any unclaimed
  key" (step 3, step 5) now means any unclaimed key in that TOPIC's fixed-size
  box, because several topics run at once. Where this ADR says the parallelism
  ceiling is the key count, read: the box size.
- **Amended by:** [ADR-0083](0083-least-spent-load-balancing-within-a-box.md) --
  the per-group **pin** is off for generation work. A group's card run no longer
  binds to one key; each call picks the least-spent key *in the box* fresh
  (`KeyClaim.sticky=False`, `key_scope="box"`), and the gate goes pool-wide
  (`"pool"`). The claim and its box scope remain; only the "one key for the
  whole run" heuristic is gone -- `cell_lock` was always what made an rpm
  violation impossible, not the pin. Read this ADR's "one key per subtopic
  group" as "one caller per cell per call".

- **Amends:** [ADR-0028](0028-key-model-quota-ladder.md) (the ladder is now walked
  own-key-first, not model-major-across-keys for every call) and
  [ADR-0065](0065-quota-governor-fairness-accounting-and-terminal-states.md)
  (least-spent-first now orders *key claims*, not individual calls).
- **Reframes:** [ADR-0040](0040-per-cell-call-serialization.md) and
  [ADR-0047](0047-removal-of-legacy-concurrency-semaphore.md) — both stay correct
  and stay in the code; this ADR makes the situation they defend against rare
  rather than routine. See "What survives from ADR-0040 / ADR-0047" below.
- **Changes:** [ADR-0026](0026-one-shot-generation-to-completion.md)'s and
  [ADR-0041](0041-per-group-gate-and-persist.md)'s placement of question
  generation — cards still persist per group, questions no longer do.
- **Does not touch:** [ADR-0073](0073-worker-runs-generation-jobs-sequentially.md).
  Jobs still run one topic at a time; this governs concurrency *inside* one run.
  (No longer true since ADR-0082: several topics run at once, each with its own
  box. This ADR still governs concurrency inside one of them.)

## Context

Concurrency inside a generation run is currently invisible. A run fans out one
LangGraph `Send` branch per subtopic group, unbounded (ADR-0047 removed the old
global semaphore, and the dead `max_concurrent_generation_calls` setting it left
behind is deleted alongside this ADR). Every call those branches make then
contends for keys individually: `QuotaGovernor.acquire()` walks the ladder
model-major, picking the least-spent key for *that one call*, and the actual
send is serialized per `(key, model)` cell by `cell_lock` (ADR-0040), with a
trailing-60s window per cell deciding whether there is room at all.

That works, and it is heavily defended — but the safety is emergent rather than
structural. Nothing in the design states how many requests can be in flight; the
answer falls out of the interaction between an unbounded fan-out, a per-call key
scan, a per-cell lock, and a learned RPM ceiling that halves on a 429 and grows
back on success (ADR-0065). Reasoning about "can this burst?" means simulating
four mechanisms at once, and the honest answer is "not usually".

Where the burst exists, it is real. A subtopic group's *drafting* is serial by
data dependency — each round's prompt carries the previous round's titles and
rejection feedback — but its gate phases fan out across the group's difficulty
tiers via `asyncio.gather`. A three-tier group can therefore put roughly six to
nine thinking-pool calls in flight at once, against a `gemini-3.7-flash` cell
whose ceiling is 5 RPM.

The owner's ask is to make the bound a *property of the design* rather than an
outcome of the machinery: give a subtopic group its own key and let it keep it.
Then the parallelism ceiling is the key count, stated in one sentence, and RPM
pressure on any single cell is bounded by the fact that only one thing is ever
using it.

Two facts make this affordable now that did not hold when ADR-0047 was written.
`SPOIN_GEMINI_API_KEYS` holds **33 keys**, and ADR-0073 made the worker run one
topic at a time — so a run's demand is one topic's subtopic groups, not several
topics' at once. The utilization ADR-0047 fought for is no longer the binding
constraint; predictability is.

A separate, unrelated correction rides along. The thinking ladder led with
`gemini-3.7-flash` from ADR-0028 onward. It was silently flipped to
`gemini-3.6-flash` first in commit `f2f63e5` ("Feat/ascii mermaid fixes and task
docs", PR #17) — a two-line reorder buried in a large ASCII-library curation PR,
unrelated to that PR's subject and with no reasoning recorded anywhere in it.
That was a regression, not a decision. The order is restored, and recorded here
so it does not quietly flip back a third time.

## Decision

### 1. The subtopic group is the unit of key ownership

A subtopic group claims one key for the whole of its **card** work — the
`plan_cards` call, every draft round, both quality-gate passes, and every
redraft round — and releases it when the group clears its completion bar.

**Parallelism equals usable key count.** At most K groups run at once, K = 33
today. Group K+1 waits for a claim; it does not start on a shared key.

**One concurrent user per key, always.** A group never borrows a key another
group holds. This is what makes an RPM violation structurally impossible rather
than merely counted: no cell can have two callers racing it.

### 2. Model selection is own-key-first

For a group holding key X that needs a thinking-pool call, in order:

1. **X's `gemini-3.7-flash`** — if it has RPD room and window room.
2. **X's `gemini-3.6-flash`.**
3. **Any unclaimed key** with room on 3.7 or 3.6, chosen least-spent-first
   (ADR-0065's ordering, now applied to claims). The group re-claims it and
   releases X.
4. **X's `gemini-3.5-flash`.**
5. **Re-check for an unclaimed key** with room.
6. **Wait** for a key to become free, then retry from step 1.

This deliberately prefers X's *second-best* model over another key's best one.
Steps 1–2 keep a group on the key it already holds, which is the whole point of
the claim; step 3 is what stops a group stranding itself on a dying key.

`gemini-3-flash-preview` is **held out of that ladder as a reserve**. It is
reached only when no key anywhere has RPD room on 3.7, 3.6 or 3.5 — that is,
when the day's real thinking budget is gone. It is never reached because keys
are *busy*: contention is waited out (step 6), exhaustion descends.

The distinction matters because the two waits are nothing alike. Waiting for a
claim or a window resolves in seconds. Waiting for RPD resolves at midnight UTC.
Collapsing them would either stall a run for hours or spend the reserve on
ordinary contention.

Ladder drain across keys stays model-major within each step — 3.7 across all
free keys before 3.6 across all free keys — which is already how
`_acquire_locked`'s outer `for rung in self.ladder` loop behaves.

### 3. The 60-second window is anchored to the send, not the grant

Already true (`note_request_sent`, ADR-0040) and explicitly retained: the
`QuotaRequest` row's `sent_at` is re-stamped in place at the true send moment, so
our window and the provider's agree on which minute a request belongs to.

The **slot is still claimed at grant time**, by `_try_reserve_rpm`'s single
`INSERT ... SELECT ... WHERE (count in window) < rpm`. That atomicity is not
negotiable — split into a count and an insert, two processes both read "4 of 5"
and the provider gets 6. Reserve early so the check is safe; re-stamp late so
the window is truthful. Both, not one.

### 4. Questions run after the whole topic's cards, not per group

Question generation moves out of `_process_gate_item`. A group's branch now does
cards only: gate, persist, redraft to bar. The fan-in node `gate_and_persist` —
today a lightweight aggregate-and-mark-done step — becomes the topic's question
phase, fanning out per subtopic-tier once **every** group has cleared its bar.

Questions are generator-pool calls (flash-lite, 500 RPD per cell, ADR-0029), so
this phase claims keys under the same rules but is not meaningfully quota-bound.

### 5. Restore the thinking ladder's model order

`gemini_thinking_ladder` leads with `gemini-3.7-flash` again. See Context.

## Consequences

**Easier**

- **The concurrency bound is one sentence.** "At most K subtopic groups, one key
  each." No simulation of four interacting mechanisms to answer "can this
  burst?".
- **Per-cell RPM contention stops existing** in the normal path. One user per
  key means `cell_lock` is uncontended, so the grant-to-send gap collapses to
  milliseconds — which in turn makes phantom grants (ADR-0061's
  `prune_request_window` refund) nearly stop happening.
- **The B4 quota panel gets a real story to tell**: keys claimed, keys free,
  groups waiting.
- **A group's whole card run shows up under one key** in the ledger, so a
  pathological subtopic is attributable instead of smeared across 33 keys.

**Harder**

- **Keys idle while claimed.** A group doing a serial draft round uses roughly
  5 RPM of a 15 RPM flash-lite cell. Under the old scheme other groups' calls
  filled that headroom; now they cannot. This is a deliberate, measured loss of
  the exact utilization ADR-0047 was written to win — accepted because ADR-0073
  already caps demand at one topic per pass.
- **A group can block on an unrelated group.** With all K keys claimed, group
  K+1 waits, even when a claimed key has budget sitting unused. Option 1's cost,
  taken knowingly: a rare stall is a better failure than a shared cell.
- **Multi-tier groups still fan out onto their single key.** A three-tier
  group's gate phase issues roughly six to nine concurrent thinking calls
  against one cell at 5 RPM. The window still throttles them correctly — they
  queue rather than 429 — but this is the one place where the "no waiting
  needed" simplification does not hold. Serializing the per-tier gate within a
  group is the fix if it bites; most groups are single-tier and unaffected.
- **A topic now has cards without quizzes for longer.** The window used to be
  per group and short; it is now the whole topic's card phase. Quiz-gated
  progression (ADR-0009) means those subtopics are not completable until the
  question phase lands. An already-reachable state — `cards_missing_questions`
  exists precisely because it is — but a wider one.
- **A crash after the card phase loses the whole topic's question work**, where
  before each group's questions were committed with its cards. The pipeline is
  idempotent per topic (ADR-0026) and `cards_missing_questions` backfills, so
  this costs a re-run, not data.

**Committed to**

- **A group never shares a claimed key.** If throughput demands it later, the
  answer is a stated concurrency number above K, decided here — not a silent
  relaxation into borrowing.
- **The preview rung stays a reserve.** It is not promoted into the ordinary
  ladder to buy throughput.
- **`cell_lock`, the atomic RPM reservation, and the send-time re-stamp all
  stay.** See below.

### What survives from ADR-0040 / ADR-0047

Neither is superseded, and neither should be deleted as "no longer needed":

- **`cell_lock` (ADR-0040)** still guards the multi-tier gate fan-out named in
  "Harder" above, and still guards every path where two processes — the API and
  the worker both read the same ledger — reach the same cell. Its contention
  becomes rare, not impossible.
- **ADR-0047's removal of the global semaphore stands.** This ADR does not
  reintroduce one. A key claim is not a global concurrency cap wrapped around
  every call; it is ownership of a specific resource for a specific unit of
  work, and it scales with the key pool exactly as ADR-0047 wanted.

### Budget after this change

At 33 keys:

| Pool | Models × RPD | Per key/day | Pool total/day |
|---|---|---|---|
| thinking, normal path | 3 × 20 | 60 | **1,980** |
| thinking, preview reserve | 1 × 20 | 20 | **660** |
| generator (flash-lite) | 2 × 500 | 1,000 | **33,000** |

A 25-card subtopic-tier costs roughly 8–12 thinking calls and about 8 generator
calls, so the normal-path thinking budget gates on the order of 160–250
subtopic-tiers per day. Generator quota is not a constraint at this scale.

## Alternatives considered

**Keep per-call key selection (the status quo).** Highest utilization: every
call goes to the coldest cell, so no key idles while another queues. Rejected
because the concurrency bound stays emergent — being able to state the ceiling
is the property that was asked for, and no amount of correct machinery
underneath substitutes for it.

**Borrow a claimed key when none is free, letting the window arbitrate.** Never
stalls; the trailing-60s counter is already correct for concurrent users, so
nothing would actually 429. Rejected: it trades the structural guarantee for a
statistical one. The whole value of the claim is being able to say a cell has
one user, and an escape hatch used under load is used exactly when it matters
most.

**Cap parallelism below the key count** (e.g. 20 groups against 33 keys, 13 held
purely for fallback). Makes both stalls and borrowing rare. Rejected as a tuning
knob that has to be justified and re-justified; "K groups, K keys" needs no
number chosen, and waiting is already acceptable at current volume.

**Claim strictly, with no fallback to another key.** The simplest possible rule.
Rejected outright: a key exhausting mid-run would strand its group with no way
forward, and at 20 RPD per thinking cell that is the common case, not an edge
case.

**Promote `gemini-3-flash-preview` into the ordinary ladder.** Four working
rungs instead of three, roughly 660 more thinking calls a day. Rejected: it is
the weakest model on the list, and these are the calls with a real consequence
if the model is weak — curriculum, judging, grading (ADR-0008). Better to stop
and resume tomorrow than to fill the corpus with content the strongest models
never saw. Holding it in reserve keeps it available for the case where stopping
is worse than degrading.

**Keep questions per group.** No graph change, and cards go live with their
quizzes attached. Rejected on the owner's call: a topic's question phase seeing
the finished card set is worth the delay, and it makes the question budget a
whole-topic decision rather than a per-group one.

## Revisit when

- **Groups routinely wait on key claims.** That is the signal that K is the real
  constraint. The answer then is more keys first — this design scales linearly
  with them — and only then a stated shared-key concurrency number.
- **The preview reserve gets spent regularly.** It means the three-rung normal
  path is undersized for actual volume, and the question becomes a paid tier or
  more projects, not promoting the weakest model.
- **Multi-tier groups become common** (curricula giving most concepts two or
  three tiers). Then the per-group gate fan-out onto one cell stops being a
  corner case and should be serialized per tier.
- **The worker stops being a one-topic-at-a-time cron pass** (ADR-0073's own
  revisit condition). Two topics in flight doubles demand for claims, and the
  key-count ceiling would need re-deriving against real numbers.
