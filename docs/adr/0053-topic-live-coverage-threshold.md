# ADR-0053: A topic is discoverable once 50% of its subtopics are covered

- **Status:** Accepted
- **Date:** 2026-08-23
- **Deciders:** Anubhav
- **Amends:** [ADR-0026](0026-one-shot-generation-to-completion.md) (resolves its "Open
  question: what happens to ADR-0006's feed-serving behavior?" section, specifically the
  read-path/discoverability half of it)

## Context

`request_topic` mints a `Topic` row and subscribes the requester immediately, before a
single card exists — generation runs after, asynchronously (ADR-0003). Nothing has ever
gated when that `Topic` row starts showing up for everyone *else*: `TopicsService.list_all`
and `.discover` (`topics/service.py`) select every `Topic` unconditionally, ordered by
`subscriber_count`. A brand-new custom topic is browsable in the "Topics" modal and
Discover the instant it's created — often for several minutes before its curriculum call
even returns, let alone before any card exists to read.

ADR-0026 flagged this gap explicitly and left it open: "whether `POOL_LOW`/`POOL_HIGH`
still mean anything... is a feed-serving/read-path question this ADR deliberately leaves
open." Building the requester-facing progress UI (RequestTopicBox/GenerationProgressPanel,
this session) forced the question: the requester needs to see real-time progress from the
moment they ask (they already follow it, so the feed serves whatever's ready per subtopic
group — `generation-pipeline.md`'s "goes live in the feed as soon as ITS OWN group is
done"), but a *stranger* browsing Discover has no such relationship and no reason to be
shown a topic that's still mostly empty.

## Decision

**A topic is "live" — visible in `list_all`/`discover` to a user who doesn't already follow
it — once at least `topic_live_coverage_fraction` (0.5) of its subtopics have individually
reached their own `min_cards` coverage threshold.** Config: `Settings.topic_live_coverage_fraction`
(`core/config.py`), computed at read time in `TopicsService._live_topic_ids` — a query
against live `Card`/`Subtopic` state, not a cached flag, so it needs no backfill and stays
correct if content is later rejected or superseded.

A topic the caller already follows (`UserTopic` row exists) bypasses this filter entirely —
`list_all`'s existing "browse everything should still show what you're already following"
principle extends naturally to "including the one you're still waiting on."
`generation_progress` exposes the same computation as `topic_live: bool`, so the requester's
own progress panel can show a distinct "now live in the feed" milestone at the exact moment
strangers start seeing it too — a separate, earlier signal than `status == "completed"`,
which can trail well behind (every subtopic still needs to finish, not just half).

**Per-subtopic coverage, not raw card count.** Reuses `min_cards` — the coverage threshold
generation already defines per subtopic (ADR-0007) — rather than introducing a second,
unrelated number. A topic with 10 thin subtopics and one with 2 deep ones shouldn't be
judged by the same flat card count; "half the subtopics individually cleared their own bar"
is the same shape of judgment the pipeline already makes per subtopic, just rolled up.

## Consequences

**Easier**

- Closes ADR-0026's open question for the discoverability half specifically (the
  feed-serving/degraded-mode half for followers is unaffected and stays open).
- No schema migration, no backfill script, no risk to the existing production corpus in
  `spoin_db` — everything is derived from `Card`/`Subtopic` rows that already exist.
- One shared helper (`_live_topic_ids`) serves both the list endpoints and the progress
  endpoint, so "what counts as live" can't drift between the two surfaces.

**Harder**

- `list_all`/`discover` now do a real aggregate query (subtopic × card join, grouped) on
  every call, where before they were a single unfiltered `Topic` select. Not expected to
  matter at the corpus's current scale (low hundreds of topics), but it's real added query
  cost against every request, not a one-time computation.
- `discover`'s `LIMIT` moved from SQL into Python (fetch all unfollowed candidates, filter
  live, then slice) — necessary because subscriber-count rank and live-coverage rank aren't
  the same ordering, but it means `discover` no longer benefits from a DB-side row cap.
- A topic can sit invisible to everyone but its requester for a while if its curriculum is
  unusually large (many subtopics, each needing real work before half the set clears) — an
  honest tradeoff of using a fraction rather than a fixed low card count, not a bug.

## Alternatives considered

**First subtopic reaches its own `min_cards`.** Fastest to reach, and mirrors the feed's own
per-group progressive-reveal language directly. Rejected for the *discoverability* surface
specifically: one covered subtopic out of a curriculum of ten reads as "barely anything" to
a stranger deciding whether to follow, even though it's a perfectly good signal for a
follower's feed (which already works this way, unaffected by this ADR).

**A fixed total active-card count (e.g. 10).** Simple, but arbitrary — doesn't map to any
existing coverage concept, and treats a topic with few large subtopics the same as one with
many thin ones. Would need its own new tunable disconnected from `min_cards`.

**Cache readiness on `Topic` (a `first_ready_at` timestamp), written by the pipeline.**
Cheaper to read (no join at list time) but requires a migration and a backfill pass over
the existing corpus to avoid every production topic vanishing from Discover the moment this
ships — real risk against `spoin_db`'s real data for a query-cost saving that isn't needed
at current scale. Revisit if `list_all`/`discover` ever show up in a slow-query report.

## Revisit when

- The corpus grows large enough that the per-call aggregate in `_live_topic_ids` shows up in
  a slow-query report — switch to the cached-timestamp alternative above.
- ADR-0026's other open half (does a follower's feed still need `POOL_LOW`/`POOL_HIGH`
  degraded-mode handling while a topic is below 100%) gets picked up — that's a separate
  decision, not resolved here.
- Real usage suggests 0.5 is the wrong number in either direction (topics feel empty when
  they first appear, or take too long to appear) — it's a config value specifically so this
  doesn't require a deploy to retune.
