# ADR-0055: The interleave plan is weighted by the current session, not long-run affinity

- **Status:** Accepted (amends 0010, 0011)
- **Date:** 2026-08-24
- **Deciders:** Anubhav

## Context

ADR-0010 builds the cross-topic interleave plan from `UserTopicAffinity` — a
slow-moving, batch-recomputed weight per (user, topic). It works, but it has no
notion of what someone is doing *right now*. A reader who opens the app and spends
ten minutes deep in one topic keeps getting the same even-handed rotation across
everything they subscribe to. The feed cannot tell the difference between "I follow
Postgres" and "I am reading about Postgres this morning."

Those are genuinely different facts and they decay at completely different rates.
Long-run affinity should take weeks to move; a session's interest should evaporate
the moment the session does. Folding both into one number means either the feed
reacts too slowly to be useful within a sitting, or a single enthusiastic hour
permanently distorts a profile that took weeks to build.

There is also a product risk in reacting to in-session behaviour at all: a feed that
chases the last thing you clicked collapses into a single topic within a few swipes,
which is precisely the failure mode that makes recommendation feeds feel claustrophobic.
Whatever we build has to be bounded on both ends — responsive enough to notice, bounded
enough that the other subscriptions survive a bad ten minutes.

## Decision

The interleave plan is weighted by a **session-scoped** engagement signal, bounded to
a fixed share band.

**A session is a run of activity with no gap of 30 minutes or more.** It is derived
server-side from the gap since the last event (`user_session_topic_signal.last_event_at`),
not from a client-minted session id. Come back in five minutes and the profile is
intact; come back the next day and it is gone.

**Cold start is uniform.** With no session activity, every subscribed topic is weighted
equally. `UserTopicAffinity` no longer feeds the plan at all — it remains untouched as
the per-card `Candidate.topic_affinity` ranking input, which is a separate concern.

**Every engagement kind contributes a configured weight** (`Settings.session_signal_weights`),
plus a per-second term for dwell. `explicit_complete` outweighs `dwell_complete`, per
ADR-0011's insistence that the two stay distinguishable. `skip` is negative — a topic
being actively scrolled past is evidence, not merely the absence of it. `impression`
contributes nothing, so the feed cannot reinforce whatever it happened to serve first.
Undoing an action subtracts exactly what taking it added.

**Each topic's share is clamped to [5%, 50%]** of the topics the feed is currently
drawing from, via `feed/session_profile.py`. Shares are solved as the single scale
factor `lam` where `sum(clip(lam * weight, lo, hi)) == 1`, found by bisection.

This lives at the plan layer, not in `ranking.py`. ADR-0010's rule is *score individual
items; enforce composition rules structurally* — the reason the difficulty mix is
stratified sampling rather than a fifth ranking weight. "How much of the feed is this
topic" is a property of the page, not of any card on it, so no per-card score can
express it.

All accumulation happens incrementally at ingest, in one atomic
`INSERT ... ON CONFLICT DO UPDATE` whose `CASE` either adds to the running score or
resets it outright when the window has lapsed. The feed read path does a plain indexed
column read, never an aggregate — ADR-0011's "no aggregation at request time" holds.

`feed_topic_run` returns to `1`. See Consequences.

## Consequences

The feed now responds within a sitting, and forgets on schedule. A user is never
locked into a taste profile they formed once.

**`feed_topic_run` goes back to 1, and per-topic headings appear per card again.**
It was 3 so the web client's headings weren't emitted before every single card. But a
run of 3 out of a 50-slot plan makes the smallest allocation a topic can win 3/50 = 6%,
which means a 5% floor is not representable in the emitted plan at all. Verified
directly: shares of `[0.50, 0.25, 0.15, 0.10]` at `run_length=3` emitted
`48% / 24% / 16% / 12%`. At 1 the granularity is 2% and the band holds. The heading
repetition is the accepted cost. Anyone raising this again must also raise `plan_size`
enough to keep one run below `session_share_floor`.

**The bounds are requests, not guarantees, and degrade predictably.** A 5% floor cannot
hold across 21 or more topics — they would sum past 100% — so above that it falls back
to `1/n` (at 25 topics, 4%). A 50% ceiling is meaningless for a single topic, which
takes the whole feed. Both are repaired to satisfy `lo <= 1/n <= hi` before solving, so
the feasible set is never empty.

**Shares are still quantized by whole plan slots.** The band is a guarantee about the
computed shares, not about the exact percentages in a 50-slot plan; expect roughly one
slot of slack either way.

**The plan rebuilds more often.** A quantized `FeedPlan.share_fingerprint` (0.05 buckets)
is now a third rebuild trigger alongside filter and topic-set changes. Without bucketing
the plan would rebuild on every single ingest. Rebuilding resets `FeedPlan.position` to
0, which is safe — `position` indexes into `topic_order`, while *which card* each topic
serves next lives in its own `FeedSlate`, untouched by a plan rebuild.

**Every weight in here is a guess.** They are config so they can be tuned against real
engagement data without a deploy, and they will need it.

**The write-side reset is lazy**, firing only on the next event. The read path therefore
re-checks staleness itself, so someone who returns the next morning and merely loads the
feed gets a clean slate rather than yesterday's profile.

## Alternatives considered

**Blend the session signal with `UserTopicAffinity` at cold start.** A topic you have
historically loved would start ahead even in a brand-new session. Rejected because it
contradicts the point: a fresh session should be open to anything, and "open to
anything" with a thumb on the scale is just a slower version of the current behaviour.
Affinity keeps its job in per-card ranking.

**A client-minted `session_id`.** The `engagement_event.session_id` column already
exists and is unused, and this is the obvious way to fill it. Rejected: it fragments
across tabs (two tabs become two sessions) and across devices (phone and laptop become
two profiles), it is client-controlled and therefore spoofable, and it needs frontend
work to deliver a worse definition of "session" than the activity gap gives for free.
The column stays unused.

**Fold the session weight into `ranking.score()` as a fifth term.** Rejected on
ADR-0010's own reasoning — a per-card score cannot express a constraint about the
composition of the page, and trying makes the share band unenforceable rather than
merely approximate.

**Compute the session profile at request time from `engagement_event`.** Simplest to
write, and it needs no new table. Rejected: it is a `SUM` over the event log on the hot
read path, which ADR-0011 rules out for exactly this shape of query.

**Pin-and-redistribute (water-filling) for the share clamp.** The intuitive algorithm —
clamp whoever violates a bound, redistribute the surplus, repeat — and it is wrong.
Pinning one topic *down* to the ceiling and another *up* to the floor in the same pass
can commit more than 100% in total, after which no number of passes makes the shares sum
to 1. Solving for a single scale factor has no such failure mode because every topic is
always measured against the same `lam`. This was caught by tests, not by review; the
regression cases are in `test_session_profile.py`.

## Revisit when

- Real engagement data exists to tune the weights against — every number in
  `Settings`'s session block is currently an informed guess.
- The per-card topic headings that `feed_topic_run = 1` reintroduces become a real
  complaint. The fix is a larger `plan_size`, not a larger run.
- Median subscription counts approach 20, where the 5% floor starts silently degrading
  to `1/n`.
- A user is observed being trapped in one topic despite the 50% ceiling — that would
  mean the ceiling is being applied to too small a topic pool, not that it is too high.
