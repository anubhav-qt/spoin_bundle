# ADR-0032: The entry tier's own quiz is still earned, not free

- **Status:** Accepted
- **Date:** 2026-08-18
- **Deciders:** Anubhav
- **Amends:** [ADR-0027](0027-self-selected-entry-tier.md) -- narrows what "entry tier is
  trusted" actually unlocks.

## Context

[ADR-0027](0027-self-selected-entry-tier.md) trusts the tier a user picks at subscribe
time and seeds `UserTopicProgress.tier_unlocked` as `True` for that tier **and every tier
below it**. Read literally, that means subscribing at Beginner -- the default, and what
every plain `POST /topics/{id}/subscribe` call does -- starts the Beginner quiz unlocked
at 0% coverage, with nothing read yet.

That was never the intent. The trust ADR-0027 is actually about is narrower: reading
skipped tiers is fine to self-certify (there's no content backing a placement quiz for
them anyway, and failing one costs nothing), but the tier you are actually about to read
and be promoted out of should earn its quiz the same way every subsequent tier does --
80% coverage, same as ADR-0009 always specified. Trusting the entry tier's *content
selection* ("start me at Intermediate") is not the same claim as trusting that the user
has already mastered it well enough to skip reading before testing out.

The bug was concrete, not hypothetical: a topic subscribed at the default Beginner entry
showed its quiz unlocked immediately, before a single card had been read.

## Decision

**Only tiers strictly below the chosen entry tier pre-unlock.** The entry tier itself
always starts locked and earns its quiz through the normal coverage gate, exactly like
every tier above it.

`_entry_tier_unlock` (`api/routers/topics.py`) changes from `rank <= entry.rank` to
`rank < entry.rank`. Concretely:

| Entry tier   | `tier_unlocked` (old, ADR-0027) | `tier_unlocked` (new, this ADR) |
| ------------ | -------------------------------- | -------------------------------- |
| Beginner     | `[True, False, False]`           | `[False, False, False]`          |
| Intermediate | `[True, True, False]`            | `[True, False, False]`           |
| Advanced     | `[True, True, True]`             | `[True, True, False]`            |

A Beginner entry -- the common case -- now behaves exactly as if no ADR-0027 special
case existed at all: there is nothing below Beginner to trust for free, so nothing is.
An Intermediate entry still gets the Beginner quiz for unlimited self-check practice
immediately (ADR-0027's actual point), but Intermediate's own quiz -- the one that
promotes to Advanced -- is earned the same way Beginner's always was.

**Everything else in ADR-0027 is unchanged:** `current_difficulty` still starts at the
chosen entry tier immediately (no gate on *what you read*, only on *what you're
certified to have passed*), and below-entry-tier quizzes are still unlimited practice
that never touches progression.

## Consequences

**Easier**

- Matches the plain reading of ADR-0009's coverage gate: every tier, including the entry
  tier, is unlocked the same way. One rule, not a special case for whichever tier happens
  to equal `current_difficulty` at subscribe time.
- No more "quiz unlocked, coverage 0%" state observable from the API -- that combination
  was the tell that something upstream was wrong.

**Harder**

- Existing `UserTopicProgress` rows written under ADR-0027's original logic keep their
  already-latched entry-tier unlock (the latch is intentionally never revoked, same
  principle as ADR-0009's coverage latch generally). Only new subscriptions get the
  corrected behavior. Not retroactively fixed, and not worth a backfill migration for a
  pre-launch product with no real users yet.

## Alternatives considered

**Drop the "tiers below entry" unlock entirely, require coverage everywhere.** Rejected:
throws away ADR-0027's actual point (an Intermediate entrant can still self-check against
Beginner material without it counting toward anything) for the sake of a fix that only
needed to touch the entry tier's own boundary condition.

## Revisit when

- If below-entry practice quizzes turn out to need the same coverage gate too (e.g. if
  they start being used as unearned proof of anything) -- not expected given ADR-0027's
  framing of them as zero-stakes self-check.
