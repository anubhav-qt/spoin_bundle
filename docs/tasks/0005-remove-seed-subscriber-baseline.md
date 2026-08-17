# Task 0005: Remove the seeded `subscriber_count` baseline

- **Owner:** unassigned
- **Timebox:** ~30 minutes
- **Depends on:** enough real `POST /topics/{id}/subscribe` traffic to make the Discover
  box's "popular" ranking meaningful without help.
- **Background reading:** [ADR-0015](../adr/0015-topic-progress-and-discovery.md)'s
  `subscriber_count` section.

## The problem

`apps/api/src/spoin/seed.py` sets `Topic.subscriber_count` directly from a
`seed_subscriber_count` fixture field in `corpus.json`, because with essentially one real
user, an honestly-counted value ties every topic at 0 or 1 -- useless for demonstrating the
Discover box's "popular" ranking. This was always meant to be temporary (see the comment
at the `topic.subscriber_count = ...` line in `seed.py`).

The column itself is real and correctly incremented by `POST /topics/{id}/subscribe` -- the
only fake part is the starting number.

## What to do

- Delete the `topic.subscriber_count = topic_data.get("seed_subscriber_count", 0)` line
  (and the fixture field, and the temporary-baseline comment) from `seed.py`.
- Decide what happens to *existing* seeded counts in a database that already has the
  fixture baseline baked in -- probably a one-off migration/script that resets
  `subscriber_count` to `COUNT(*)` over real `UserTopic` rows per topic, so a
  re-seed-free production database doesn't carry the fixture numbers forward.
- Confirm the Discover box's ranking still looks reasonable without the crutch -- if it
  doesn't (too few real subscriptions to differentiate topics yet), that's a sign this
  task is premature, not that the fix was wrong.
