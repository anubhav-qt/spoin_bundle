# ADR-0027: Self-selected entry tier; the placement quiz gate is dropped

- **Status:** Accepted
- **Date:** 2026-08-17
- **Deciders:** Anubhav
- **Amends:** [ADR-0009](0009-quiz-gated-progression.md) — drops the placement-quiz gate
  described there; promotion and mastery are unchanged.

## Context

Task 0011 (quiz backend) needed a real decision on the `placement` row of ADR-0009's
"entry, promotion, mastery" table: "Starting above beginner is not self-assessment; it
requires passing that tier's quiz." Building that gate raises real design cost with no
clear payoff — it needs its own bank-readiness check (a brand-new subscriber has read
nothing, so what content backs a placement quiz for intermediate?), its own retry
semantics distinct from promotion, and a decision about what happens when the bank for
that tier doesn't exist yet.

Asked directly, the product decision came back simpler than the ADR assumed: entry tier
is a preference, not an achievement to gate. What's actually worth protecting is
*promotion past your entry tier*, which content-model.md's coverage gate already
handles.

## Decision

**Entry tier is trusted, unconditionally.** Subscribing at Intermediate sets
`current_difficulty = intermediate` immediately — no quiz stands between choosing a tier
and reading it. `UserTopicProgress.tier_unlocked` is initialized `True` for the chosen
tier and every tier below it (so `[True, True, False]` for an Intermediate entry), same
array, same latch semantics ADR-0009 already defined — just seeded at subscribe time
instead of earned solely through coverage.

**Quizzes at or below `current_difficulty` are open for unlimited practice retries.** A
user who entered at Intermediate can take the Beginner quiz any time, purely for
self-check — it never changes `current_difficulty`, `tier_quiz_passed`, or anything else
in `UserTopicProgress`. This reuses `QuizKind.PLACEMENT` as its label (no migration:
storage stays a three-value enum, only the *meaning* of one value changes — "an
attempt that doesn't drive progression" rather than "an entry gate").

**Promotion and mastery are unchanged from ADR-0009.** Passing the quiz for your current
tier (once 80%-coverage-unlocked) still advances you to the next tier; the advanced-tier
mastery quiz still requires `tier_content_complete[advanced]` first. The coverage gate is
still the only thing that can't be skipped by picking a tier and typing well on one quiz.

## Consequences

**Easier**

- No bank-readiness problem for a zero-content placement quiz — there is no such quiz.
- One fewer state to test: `QuizAttempt.kind` still has three values, but only two
  (`promotion`, `mastery`) write to `UserTopicProgress`.
- Below-entry-tier quizzes are a genuine practice feature (content-model.md's "discovery
  tool" framing) rather than dead weight nobody could reach twice.

**Harder**

- A user can claim Advanced at signup with zero verification and read advanced content
  immediately. This is an accepted tradeoff, not an oversight: content quality is not
  gated by claimed tier anywhere else in the system either (the feed mixes by
  *earned* `current_difficulty`, and that mix is what's protected here).
- `QuizKind.PLACEMENT`'s name no longer matches its behavior 1:1 (see Decision) — a
  reader of `domain/models/quiz.py` needs this ADR to understand why an attempt kind
  called "placement" never changes placement.

## Alternatives considered

**Keep the gate, but waive the coverage prerequisite for placement specifically.**
Rejected: still needs a bank-readiness answer for a subscriber who hasn't read anything,
and still adds a whole quiz flow whose only job is to confirm what the user just typed
into a picker.

**Rename `QuizKind.PLACEMENT` to `PRACTICE`.** More honest, but a native Postgres enum
rename is a migration for a cosmetic gain; deferred until the enum needs to change for
another reason anyway.

## Revisit when

- Users self-report entering at a tier they can't actually handle (a real trust signal,
  not a hypothetical) — reconsider a lightweight (not gated) diagnostic instead of a
  pass/fail quiz.
- `QuizKind.PLACEMENT`'s repurposed meaning causes a real bug (someone assumes it still
  gates entry) — that's the signal to spend the rename migration.
