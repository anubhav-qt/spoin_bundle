# Task 0003: Personalized "for you" topic recommendations

- **Owner:** unassigned
- **Timebox:** ~2 days
- **Depends on:** [ADR-0015](../adr/0015-topic-progress-and-discovery.md) (the Discover
  box and its `mode=popular|for_you` toggle, which this task gives real teeth).
- **Background reading:** [`apps/api/src/slocho/feed/service.py`](../../apps/api/src/slocho/feed/service.py)
  (how `UserTopicAffinity` is read for feed ranking today).

## The problem

`GET /topics/discover?mode=for_you` exists and the frontend toggle is fully wired, but
`for_you` currently runs the **identical query** as `popular` (rank by
`subscriber_count DESC`, excluding followed topics). There is no dishonesty in this — the
route is a real branch point, just unimplemented on one side — but it means the toggle
does nothing visible yet.

`UserTopicAffinity` (`user_id`, `topic_id`, `affinity: float`) is the closest existing
signal, but it only ever has rows for topics a user **already follows** — it's read by the
feed ranker to weight the interleave plan, never written for topics outside a user's
`UserTopic` set. There is currently no path from "user likes Kubernetes a lot" to
"recommend Docker."

## What we need from you

A real ranking for `for_you`, using *something* — not decided yet, on purpose. Candidates,
roughly in order of how much new infrastructure each needs:

1. **Embedding similarity to followed topics.** Every `Topic` already has an `embedding`
   (ADR-0004). Rank unfollowed topics by similarity to the topics the user already
   follows, weighted by that topic's `UserTopicAffinity` if you want followed-topic
   engagement to matter, not just follow-status. Cheapest to build — no new writes.
2. **Co-subscription patterns** ("users who follow X also follow Y"). Needs enough
   multi-user data to be meaningful, which the seeded single-demo-user environment
   doesn't have — likely not testable until there's real traffic.
3. Something else — this list isn't exhaustive, and the two above may turn out to be
   worse than a simpler heuristic once you look at real data.

Whatever you pick, write down why the alternatives lost, same as any other ADR-worthy
decision — this should probably become its own ADR once implemented, not just a code
change.

## Deliverables

- A working `for_you` ranking, distinguishable from `popular` in normal use.
- An ADR for the ranking decision.
- Updated `docs/adr/0015-topic-progress-and-discovery.md`'s "Revisit when" section, noting
  this landed.
