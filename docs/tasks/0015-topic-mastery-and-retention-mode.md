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

## Timebox

Medium -- touches feed read-path scoring, a schema addition for
last-seen/next-review timing, and new UI. Scope the ADR and the UI moment as
separate PRs from the scheduling logic itself.
