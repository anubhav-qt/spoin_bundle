# ADR-0050: Being shown a card consumes it; a difficulty turns over instead of running dry

- **Status:** Accepted
- **Date:** 2026-08-21
- **Deciders:** mayanks0ni
- **Amends:** [ADR-0010](0010-feed-serving.md) — "scrolling past never counts" now
  applies to *progression* only. It no longer means an impression changes nothing.
- **Fixes a drift from:** [ADR-0010](0010-feed-serving.md), whose own seen-state
  section already specified "the cycle advances when no `UNSEEN` cards remain at that
  difficulty across all subtopics". Nothing ever implemented that sentence.

## Context

A reader who scrolled without opening anything was served the same cards forever.

Three separate gaps produced it, and each one alone would have been enough:

1. **An impression changed nothing.** `_apply_state`'s `IMPRESSION` branch wrote
   `UNSEEN` — the state the card was already in — under the comment "scrolling past
   never counts". So a card stayed eligible no matter how many times it had been
   shown. Nothing but deliberate reading ever consumed one.

2. **The cycle counter had no writer.** `UserTopicCycle` was read in two places and
   written in none, anywhere in the codebase. `cycle` was therefore permanently `0`,
   `deferred_cycle` was permanently `0`, and ADR-0010's eligibility rule
   `deferred_cycle < current_cycle` evaluated `0 < 0` — false, always. The
   second-chance pass could not happen even in principle. The model's own docstring
   promised the behaviour; no code delivered it.

3. **Nothing ever deferred a card.** The only kind reaching `_defer` was `SKIP`, and
   the client never emits it — `"skip"` exists solely as a member of the
   `EngagementKind` union in `lib/api.ts`, referenced by no component.

ADR-0010 anticipated exactly this failure and said so plainly: *"Deferred-card
cycling is genuinely fiddly and needs real test coverage. A bug here shows as 'I keep
seeing the same cards', which is the most damaging feed bug there is."*

There **was** a test. `test_deferred_cards_return_only_after_the_cycle_advances`
passed because it inserted `UserTopicCycle(cycle=1)` by hand, with the comment
"advance the cycle, as the worker does once no UNSEEN cards remain." No worker did.
The test supplied the one piece of state production code never produced, and so
proved the half of the mechanism that worked while hiding the half that did not.

The product consequence: Spoin is meant to be scrollable the way a social feed is,
where reading is opt-in. A feed that can only advance for someone who reads is a
feed that stalls for its most common visitor.

## Decision

**Being shown a card consumes it. Reading a card is what counts.** Those become two
different things.

- **An impression marks the card `DEFERRED`**, not `UNSEEN`. It leaves rotation until
  the difficulty turns over.
- **The client only emits an impression after 1000ms of continuous ≥50% visibility.**
  An impression now costs the reader a card, so it has to be earned; without a
  threshold one fast flick down the feed would burn everything it passed.
- **`_maybe_advance_cycle` implements ADR-0010's sentence.** A difficulty turns over
  when **no `UNSEEN` remain** *and* **something is actually deferred**. Both
  conditions are load-bearing: advancing with nothing deferred would quietly paper
  over a starved pool that should be reported and generated into instead. It runs
  only when a stratum comes back empty — two `EXISTS` queries on a path that was
  about to serve nothing.
- **A repeat pass shuffles rather than ranks.** By the second pass `coverage_need` is
  ~0 everywhere and quality/recency would hand back the same order every cycle,
  making a re-read feel like a replay. `diversify` still applies, so one subtopic
  cannot clump.
- **The repeat is announced once**, via a `recycling` flag on the feed response. An
  unexplained repeat reads as a bug, and ADR-0006 is explicit that these states are a
  design surface rather than an error path.

**`DEFERRED` stays out of progression.** `_bump_subtopic_progress` counts
`state == SEEN` exclusively, so being shown a card advances the 80% coverage gate by
exactly nothing. ADR-0010's "speed-swiping earns nothing" is preserved in the sense
that matters: scrolling gets you an endless feed, never a quiz unlock.

## Consequences

**Easier**

- The feed advances for a reader who does not read, which is the behaviour the
  product was always described as having.
- ADR-0010's three-state model finally behaves as written, so the ADR can be trusted
  as a description of the system rather than of an intention.
- "I keep seeing the same cards" stops being reachable through the common path.

**Harder**

- An impression is now destructive, so its threshold is a real tuning parameter with
  a bad failure mode on each side. Too low and a scroll burns a slate; too high and
  the feed stalls again. 1000ms is a starting point, not a measured value.
- Cards genuinely repeat now. Duplicate suppression on the client had to be narrowed
  from "every card this session" to a 40-card window — the session-wide version would
  have swallowed the entire repeat pass and reported the feed exhausted at the exact
  moment it finally had more to give. That window is now the thing standing between a
  legitimate repeat and the adjacent-duplicate bug, and it is a heuristic.
- Read cards never return. A reader who genuinely finishes a difficulty still runs
  out, and only a quiz moves them up. This ADR does not address that.

**Committed to**

- Coverage counts `SEEN` and nothing else. Any future state that also implies
  "the reader engaged" must not be folded into that count without its own ADR.
- A difficulty turns over only when something is waiting to be released. Turning over
  an empty difficulty would hide starvation.
- Any test asserting the cycle behaviour drives it through the service. Writing
  `UserTopicCycle` directly from a test is what let this bug live.

## Alternatives considered

**Recycle `SEEN` cards too, once the deferred pile is also drained.** The literal
reading of "repeat them all once the difficulty is finished", and rejected for now.
`SEEN` is load-bearing for the 80% gate and `UserSubtopicProgress.seen_count`;
returning those cards to rotation means either double-counting coverage or teaching
every counter to ignore repeats. Since a scroller marks almost nothing `SEEN`, the
deferred pile alone already delivers the endless feed. Revisit if readers who
*do* read start hitting the wall.

**Mark a card consumed the moment it is served, in `build_slate`.** Simplest possible
rule and no client change. Rejected: serving is not seeing. A card at the bottom of a
page the reader never scrolls to would be burned unseen, and the reader would never
know what they missed.

**Advance the cycle from a batch job**, as the old test's comment imagined. Rejected:
it puts a user-visible latency between "ran out" and "has more", for a decision that
is one `EXISTS` query on a path already known to be empty. Nothing about it needs to
be asynchronous.

**Key the difficulty-mix ramp off cards shown rather than cards read.** Considered
and deliberately not done. `dynamic_mix` holds a reader at 100% of their own tier
until they have read 20% of it, so a scroller never sees the 20% intermediate slice.
Loosening that would hand people harder cards they have no grounding in, which is the
ramp's entire purpose — and since tier promotion requires passing a quiz, a scroller
stays at their tier regardless. Left alone until the simpler fix has been felt.

## Revisit when

- Readers who actually read report running out. That is the signal the `SEEN`
  alternative above is now worth its complexity.
- The 1000ms impression threshold is measured against real scroll behaviour rather
  than assumed. Either failure mode showing up in engagement data should move it.
- `FeedPage.starved` gains a consumer. It currently has none — the router drops it
  and no fill job is enqueued from a starved read, so ADR-0006's demand-driven fill
  loop is only half-wired. Recycling keeps the feed moving over a corpus that is too
  small, which makes that gap easier to ignore and more important to close.
