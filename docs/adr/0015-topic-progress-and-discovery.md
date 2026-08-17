# ADR-0015: Per-topic progress box, engagement-stats modal, and topic discovery

- **Status:** Accepted
- **Date:** 2026-08-16
- **Deciders:** Anubhav

## Context

Restructuring the right rail (extending [ADR-0014](0014-progress-insights-panel.md)) past
"less blank space" into real content: a global "take a quiz" button becomes a per-topic
progress list; clicking a topic opens the app's first modal with detailed stats; "Explore"
in the left nav becomes a real Discover surface. Each of these needed a small, honest
backend decision rather than just UI wiring.

### Per-topic quiz gating replaces the global button

`QuizCTA` asked "is _any_ followed topic quiz-ready" and showed one button. That collapses
information the user already has per-topic (`TopicProgress.quizUnlocked`) into a single
bit. `TopicsProgressBox` shows one row per followed topic -- name, coverage bar, and a
per-row quiz pill that enables at 80% -- using data the client already fetches. No new
backend surface for this half.

### The stats modal needed a real aggregate query, and the sources aren't uniform

Likes and saves have current-state tables (`CardLike`, `CardBookmark` -- per user, per
card, straightforwardly joinable to `Card.topic_id` for an exact count). Notes and shares
do **not**: `CardNote` (meant to hold note text) has zero writers anywhere in the codebase
today -- the Note button only fires a bare `EngagementEvent`, no text is captured. Same for
Share. So `GET /topics/{id}/stats` sources likes/saves from their state tables and
notes/shares from `COUNT(*) ... WHERE kind IN (note, share) GROUP BY kind` over the raw
event log -- the most accurate source available for each, not a single uniform query.
`ask_ai` is intentionally excluded, per instruction -- it isn't a comprehension/ownership
signal the way the other four are.

**Not building right now, explicitly deferred:** an "all my notes in one place" view. That
needs `CardNote` to actually store text somewhere first, which nothing does today -- see
task [0004](../tasks/0004-notes-in-one-place.md).

### Discovery needed topics nobody follows, which the seed data didn't have

Every topic `seed.py` created was also auto-subscribed to the demo user -- there was no
pool for a "discover" surface to draw from. Fixed at the source: `apps/fixtures/corpus.json`
gained a `subscribe: true|false` field per topic, and 4 new topics (Docker, Rust, Linux
Networking, GraphQL) ship unsubscribed alongside 2 new subscribed ones (React,
PostgreSQL -- also satisfies wanting more filter chips to demonstrate overflow).

`GET /topics/discover?mode=popular|for_you` ranks by `Topic.subscriber_count DESC`,
excluding topics the user already follows (a discovery surface should show what you don't
have). Both modes run the identical query today -- there is no way to personalize
_unfollowed_ topics yet: `UserTopicAffinity` (used for feed ranking) only ever has rows
for topics a user already subscribes to. The `mode` param exists so the frontend toggle is
real and the future personalized path has somewhere to land without a route shape change.
Real personalization is task [0003](../tasks/0003-personalized-topic-recommendations.md).

### `subscriber_count` needed a seed baseline, temporarily

`Topic.subscriber_count` (`topic.py:81`) was modeled but never written -- its own comment
claimed a "batch job" that doesn't exist. With effectively one real user, an honestly
_counted_ value ties every topic at 0 or 1, which makes "popular" meaningless. `seed.py`
now sets a fixture baseline per topic (`seed_subscriber_count` in `corpus.json`) directly,
clearly commented as **temporary** -- task [0005](../tasks/0005-remove-seed-subscriber-baseline.md)
tracks deleting it once `POST /topics/{id}/subscribe` (new -- the app's first real follow
action, increments the same column) has enough organic traffic to stand on its own. The
column and the increment are real; only today's starting numbers are seeded.

### Discovery is the one place `canonical_name` is shown, not `display_name`

ADR-0004's rule is "always the user's own label, never canonical" -- but that rule
presupposes a `UserTopic` row exists. A topic surfaced by Discover has none yet (that's
the point), so `TopicDiscoverOut.display_name` is `Topic.canonical_name` by necessity, not
by exception to the rule. Once followed (via `/subscribe`), the row gets a real
`UserTopic.display_name` (defaulted to the canonical name -- no rename UI exists yet) and
every other surface goes back to the normal rule.

## Consequences

**Easier**

- The stats modal, the progress box, and Discover are all additive -- nothing about
  `/topics/{id}/progress` or the feed changed.
- `subscriber_count` and `UserTopicAffinity` are both real columns now exercised by real
  code paths (the new subscribe endpoint, the existing feed ranker) -- the seed-baseline
  caveat is the only fake part, and it's narrow and tracked.

**Harder**

- `for_you` and `popular` are indistinguishable in the UI right now beyond the label --
  worth watching whether that reads as broken before task 0003 lands.
- The Discover list will look static until `/subscribe` traffic outpaces the seed
  baseline; task 0005 is what removes the training wheels.

## Alternatives considered

**Skip the modal, show stats inline in the progress row.** Rejected: four extra numbers
per row (on top of name + bar + quiz pill) would recreate the "congested chip" problem
this whole pass was trying to fix.

**Compute `for_you` from embedding similarity to followed topics right now.** Rejected:
real scope creep for this pass, and would bake in an unreviewed ranking heuristic. Task
0003 exists so that gets designed deliberately instead of improvised here.

## Revisit when

- Task 0003 lands -- `for_you` gets real logic, this ADR's "identical query" note is stale.
- Task 0005 lands -- the seed baseline is gone, `subscriber_count` is fully organic.
- Task 0004 lands -- note-taking actually stores text, and "all my notes" becomes buildable.
