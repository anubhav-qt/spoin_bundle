# Task 0024: Re-introduce the custom-topic limit as a premium gate

**Owner:** unassigned

## The problem

The three-custom-topic-per-user cap (`content-model.md`'s "Custom topics" section)
has been removed entirely, config field included. `TopicsService.request_topic`
(`apps/api/src/spoin/topics/service.py`) no longer counts `UserTopic.is_custom` rows
or rejects past a threshold, and `Settings.custom_topic_limit`
(`apps/api/src/spoin/core/config.py`) no longer exists — any signed-up user can
request as many custom topics as they want.

This was a deliberate, temporary removal (2026-08-24), not a bug fix. The limit was
originally free-tier-only friction; `content-model.md` already noted "Unlimited is a
planned premium feature." Pulling it out now unblocks testing/dogfooding without the
cap getting in the way; it needs to come back once there's an actual free/premium
split to gate on.

## Why it matters

Without a cap, a single user can spend unbounded generation quota (ADR-0028's key
ladder) minting custom topics — fine while the product is pre-monetization and the
team is the only heavy user, not fine once real users show up without a tier to
distinguish "free" from "pays for unlimited."

## What to do

1. Re-add a `custom_topic_limit: int` field to `Settings` (`core/config.py`), and
   reinstate the server-side check in `request_topic` (was previously right after
   the word-count check, before the LLM name-validation call — keep it there; that
   ordering was a deliberate perf fix, see git history around 2026-08-24).
2. Decide the actual gate: still a flat limit for everyone, or free-tier-only with
   premium users exempted (needs a tier field on `User` that doesn't exist yet).
3. Restore or rewrite `test_custom_topic_limit_enforced_server_side` in
   `apps/api/tests/test_topics_request.py` (removed alongside the enforcement).
4. Restore the "Up to 3 custom topics" hint copy in
   `apps/web/components/RequestTopicBox.tsx` (or whatever copy matches the real
   gate — flat limit vs. premium upsell reads very differently).
5. Update `content-model.md`'s "Custom topics" section once the real shape is
   decided — it currently still describes the three-topic cap as enforced, which
   will be stale until this lands.

## Timebox

Small if it's just restoring the flat limit (~15 minutes); larger if it's gated on
an actual premium tier, since that requires the tier field and its own design.
