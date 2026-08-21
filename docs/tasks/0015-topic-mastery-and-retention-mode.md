# Task 0015: Topic mastery message + retention/spaced-repetition mode

**Owner:** unassigned

## The problem

Once a user has read every card at every difficulty tier in a topic (including
expert), the feed currently has nothing meaningful left to serve for that
topic — it either falls back to repeating SEEN cards indistinguishably from
new ones, or goes quiet, with no signal to the user about *why*.

## Why it matters

"You've run out of new cards" reads as a dead end today. It should read as an
achievement: the user just finished mastering a topic. That moment is worth
naming explicitly, and it's also the natural trigger for two things that are
good for retention on their own: spaced-repetition review of what they've
already read, and a nudge toward quizzes (the thing the mastery is actually
tested by) and new topics.

## What to do

1. Detect topic completion server-side — likely `UserTopicProgress` reaching
   100% coverage across all difficulty tiers (the same aggregate the 80%
   quiz-gate already reads from, see ADR-0009/ADR-0011).
2. On completion, surface a one-time "you've mastered this topic" moment in
   the feed UI rather than silently degrading — a distinct card or banner,
   not a toast that can be missed mid-scroll.
3. Design what "revisit from time to time" means concretely: a scheduling
   rule (e.g. SEEN cards become re-eligible after N days, prioritized by
   spaced-repetition-style recency of last read rather than plain randomness)
   feeding into `feed/ranking.py`'s existing scoring, not a parallel system.
4. Surface incomplete quizzes for the topic and a "try a new topic" nudge
   alongside the mastery moment — reuses `TopicDiscoveryModal`/
   `RequestTopicBox` rather than inventing a new flow.
5. Write the ADR for the spaced-repetition scheduling rule before
   implementing it — it changes SEEN-state semantics (ADR-0011), which needs
   the same "why" discipline as any other progression rule.

## Origin

Raised in conversation 2026-08-21: "if the user even reads all the expert
cards, then the feed will be repeated but first told that you have enough
material to master the topic, now you will revisit those from time to time,
consider doing its quizzes for retention and move to new topics." Came up
right after adding archetype-diversity to `diversify()` (feed/ranking.py) —
same session, unrelated mechanism.

## Open questions / notes for whoever picks this up

- **Mastery = card coverage, not quiz completion.** The trigger is reading
  every card at every tier including expert, per the origin quote above.
  Quizzes are a *nudge* surfaced alongside the mastery moment (retention),
  not a gate on reaching it — don't conflate this with the existing
  quiz-gated *progression* between difficulty tiers (ADR-0009), which is a
  different, already-solved mechanism.
- **Don't build revisit-scheduling from scratch — check reuse first.**
  `UserTopicCycle` already exists and already makes SEEN-adjacent cards
  re-eligible on a cycle advance (`feed/service.py`'s `_eligible_cards`,
  currently used for DEFERRED cards specifically: "DEFERRED comes back once
  the cycle advances"). A spaced-repetition revisit for fully-SEEN cards in a
  mastered topic may be a natural extension of that same cycle concept
  rather than a new last-seen/next-review column — evaluate before adding
  schema.
- **The mastery moment must be a one-time event, not re-triggered every
  session.** Needs a persisted "mastery acknowledged" flag/timestamp per
  user+topic so returning to an already-mastered topic doesn't re-show the
  banner — likely lives next to `UserTopicProgress`.
- **What "revisit from time to time" cadence should be** is undecided —
  needs a concrete rule (e.g. weighted by original freshness/quality decay
  like `feed/ranking.py`'s `score()` already does, or a fixed N-day cooldown
  per card) before implementation, not left as "eventually, sometimes."

## Timebox

Medium -- touches feed read-path scoring, a schema addition for
last-seen/next-review timing, and new UI. Scope the ADR and the UI moment as
separate PRs from the scheduling logic itself.
