# ADR-0011: Engagement -- append-only events, mutable state, derived aggregates

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Anubhav

## Context

Engagement is what makes the feed personal: it feeds ranking ([ADR-0010](0010-feed-serving.md)),
drives the progression gate ([ADR-0009](0009-quiz-gated-progression.md)), and is the only
evidence we will ever have about whether the product works.

It is also the highest-write-volume part of the system, and it is written from a client we
do not control.

## Decision

**Three distinct kinds of data, not one table.**

### 1. Append-only events (source of truth)

```
engagement_event
  id              client-generated (idempotency)
  user_id, card_id, topic_id, subtopic_id
  kind            impression | expand | collapse | dwell | skip | share | ask_ai
                  | explicit_complete | dwell_complete
  dwell_ms        nullable
  occurred_at     server-assigned
  session_id
```

Immutable, never updated, high volume. This is the truth from which every aggregate below
can be rebuilt, and it is what makes a smarter ranker possible in two years without having
thrown the data away.

### 2. Mutable state

```
card_like      (user_id, card_id, created_at)
card_bookmark  (user_id, card_id, created_at)
card_note      (user_id, card_id, body, updated_at)     private, per-user
user_card_state(user_id, card_id, state, cycle)         UNSEEN|DEFERRED|SEEN
```

These can be undone. They are rows that get updated or deleted, **and they also emit an
event** so the log stays complete.

### 3. Derived aggregates (caches, rebuildable)

```
card_stats             impressions, expands, likes, saves, avg_dwell, skip_rate
                       -> card_quality  (RATE, not count)
user_topic_affinity    per-user engagement weight per topic
user_subtopic_progress seen_count, total_count  -> the 80% gate
user_seen_bitmap       derived read model (ADR-0010)
```

**Maintained by batch jobs, never computed at request time.** The feed query reads these
columns directly. No `COUNT(*)` over the event log in a user-facing path, ever.

This is the single most important performance decision in the read path, and it is why
Redis is not required in v1.

### Completion is two events, not one

A card becomes `SEEN` via either path ([ADR-0010](0010-feed-serving.md)), but they are
recorded **separately** because they are very different quality signals:

| Event               | Meaning                         | Signal strength                                 |
| ------------------- | ------------------------------- | ----------------------------------------------- |
| `explicit_complete` | User tapped "Got it"            | **Strong.** A deliberate claim of comprehension |
| `dwell_complete`    | Tab was open past the threshold | Weak. They may have been making tea             |

For the progression gate they are equivalent. For **ranking and topic affinity they are
weighted differently** -- an explicit completion is among the highest-quality positive
signals available, arguably better than a like since it reports understanding rather than
enjoyment.

Collapsing them into one boolean discards that permanently. Unlike most modelling mistakes,
this one is _not_ recoverable from the event log, because the distinction would never have
been written down.

### Rate, not count

`card_quality` is engagement **per impression**. Raw counts make old cards permanently
dominant and new cards permanently invisible, which combined with ranking produces a
cold-start death spiral.

**This is why impressions must be logged even though they are the highest-volume event.**
Without a denominator there is no rate.

## Practical constraints

### Batch on the client

One HTTP request per scroll tick will melt a free-tier API. The client buffers events and
flushes every few seconds, on card change, and on page hide. A dropped buffer is acceptable
for impressions; it is not for `expand` (which drives progression), so expansion is sent
promptly rather than buffered.

### Idempotency

Retries and flaky networks produce duplicates. Every event carries a **client-generated id**
and ingest deduplicates on it. Without this, impression counts inflate and every rate is
wrong.

### Dwell time is the best implicit signal and the easiest to corrupt

A tab left open overnight is not a nine-hour engagement.

- Only accumulate dwell while the page is **visible** (Page Visibility API).
- **Cap** any single dwell measurement.
- Discard implausible values at ingest rather than storing them.

### Never trust the client

`occurred_at` is **server-assigned**. Client clocks are wrong, and in some cases
deliberately. Client timestamps may be stored separately for ordering within a batch, but
never used as truth.

Event ingest is **rate-limited per user**, both as abuse protection and because a buggy
client loop is indistinguishable from an attack.

## Consequences

**Easier**

- Every aggregate is rebuildable, so a bug in aggregation logic is recoverable by
  recomputation rather than being permanent data loss.
- The feed read path touches only precomputed columns.
- The raw log supports analytics and future ML that we cannot specify yet.

**Harder**

- Highest write volume in the system, on a free-tier database with limited storage. The
  event log will need a retention policy (aggregate then prune) sooner than anything else.
- Dual-write between events and derived state introduces drift; reconciliation jobs are
  required, not optional.
- Client-side batching means engagement is eventually consistent. The UI must not read back
  its own writes for anything that matters.

**Committed to**

- No aggregation in a user-facing request.
- `occurred_at` is server-assigned.
- Aggregates are always rebuildable from the event log.

## Alternatives considered

**One table for everything.** Rejected: likes are mutable state and impressions are
immutable facts, with wildly different volumes and lifetimes. Merging them makes both
awkward.

**Derived state only, no event log.** Cheaper in storage, and it discards the ability to
rebuild, to analyse, or to train anything later. Rejected: the log is the only irreplaceable
part.

**Compute aggregates at request time.** Rejected: it puts the highest-volume table in the
lowest-latency path.

**Trusting client timestamps.** Rejected for the obvious reason.

## Revisit when

- Event log storage approaches the free-tier limit -- then implement retention (roll up to
  daily aggregates, prune raw rows beyond N days).
- Write volume exceeds what the API instance can absorb -- then a queue in front of ingest.
- Reconciliation regularly finds drift, indicating a bug in dual-write rather than a
  tolerable race.
