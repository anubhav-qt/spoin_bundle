# ADR-0054: Sequential subtopic curriculum ordering and true infinite filtered feed

- **Status:** Accepted
- **Date:** 2026-08-24
- **Deciders:** Anubhav
- **Amends:** [ADR-0010](0010-feed-serving.md), [ADR-0050](0050-shown-consumes-a-card.md)

## Context

Two critical pedagogical and usability issues were present in feed serving:

1. **Subtopic Pedagogical Disconnect**: In previous feed serving, eligible cards within a difficulty tier were ranked purely by quality score, freshness, and recency without respecting the curriculum's natural subtopic sequence. As a result, learners frequently encountered cards from advanced subtopics (e.g. Subtopic 15: *Query Planning & EXPLAIN Output Analysis*) before ever seeing introductory baseline subtopics (e.g. Subtopic 1: *PostgreSQL Architecture & Process Model*).
2. **Single-Topic Filter Starvation & Premature Feed Exhaustion**: When a user filtered their feed to a single topic, once the candidate pool of unseen cards for that topic was slated or held in the deduplication window, `FeedService.page` returned `exhausted = True`. The frontend's `IntersectionObserver` immediately disconnected and displayed an abrupt "End of Feed" brick wall, breaking the core promise of an infinite learning feed.

## Decision

1. **Sequential Pedagogical Progression**:
   - The curriculum generator emits subtopics in pedagogical order, with `Subtopic.position` representing the 1-based curriculum sequence.
   - `FeedService._eligible_cards` queries select `Subtopic.position` and enforce `ORDER BY Subtopic.position ASC, Card.created_at ASC`.
   - `Candidate` carries `subtopic_position: int`.
   - `rank()` sorts candidates primarily by `c.subtopic_position ASC` before comparing linear quality/affinity/coverage/freshness scores.
   - Learners master foundational subtopics in order before progressing to later subtopics of the same difficulty.

2. **True Infinite Feed for Filtered & General Feeds**:
   - Added `_all_active_cards` fallback in `FeedService.build_slate` to replenish slates with fresh diversified recycling passes whenever all eligible cards have been traversed in the current session.
   - `FeedService.page` only sets `exhausted = True` if the topics in the plan contain genuinely `0` active cards in the entire database.

## Consequences

**Easier.** Concepts build naturally on top of earlier foundations without jumping to
advanced nuances prematurely. Users can filter to any topic and scroll infinitely without
hitting dead ends. The system transitions into diversified repeat cycles
(`recycling = true`) once all material has been read, rather than stopping.

**Harder.** Top-scoring cards in later subtopics wait until earlier subtopics have been
served, rather than dominating the top of the feed immediately. This is an intentional
pedagogical choice: correctness and comprehension precede raw engagement optimization. A
single-topic filter that never runs dry also means `FeedPage.exhausted` now means
something narrower than it used to — see ADR-0050's own note on `FeedPage.starved`, whose
"nothing currently reads this" caveat this change makes more true, not less: a topic that
is short on fresh material now recycles instead of ever reporting starved slots for a
fill job.

## Alternatives considered

- **Sorting by `Card.created_at` or `Subtopic.created_at`.** Background workers generate
  subtopics in parallel, and retry passes write cards at arbitrary times, so `created_at`
  reflects generation order, not curriculum order — a subtopic generated late would sort
  late even if it comes first pedagogically. `Subtopic.position` is assigned by the
  curriculum generator specifically to be that ordering signal, and already existed on the
  model; nothing else could substitute for it.
- **Requiring manual topic unfiltering when a topic ends.** Would have been simpler to
  ship, but it reintroduces exactly the dead end ADR-0050 already spent an ADR removing
  from the general feed, just scoped to filtered feeds instead. Users have no reason to
  expect a filtered feed to behave differently from the general one on this axis.

## Revisit when

- Revisit if users request a "shuffled/random review" mode where curriculum ordering is explicitly bypassed in favor of randomized spaced repetition.
