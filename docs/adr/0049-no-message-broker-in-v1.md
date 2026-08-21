# ADR-0049: No message broker in v1; Kafka is rejected, not deferred-by-accident

- **Status:** Accepted (extends 0003 §4)
- **Date:** 2026-08-22
- **Deciders:** Anubhav

## Context

A proposal (2026-08-22) suggested moving Spoin's backend to an event-driven
architecture on Apache Kafka, alongside the CockroachDB migration that
[ADR-0048](0048-cockroachdb-over-neon.md) accepted. Concretely: `aiokafka` in the API,
domain events (`CardDwellEvent`, `CardSwipedEvent`, `QuizSubmittedEvent`) produced on
the request path, and a stream-consumer worker folding them into affinity scores.

This ADR exists because *rejecting* that is a decision with reasoning worth keeping.
ADR-0003 §4 already said "no Redis in v1" and explained why; without an equivalent
record here, "should we put Kafka in front of engagement writes?" is a question that
gets re-asked every few months and re-answered from scratch.

The proposal also framed Kafka as part of the fix for the storage ceiling. It is worth
saying explicitly that those are unrelated problems — a broker does not store a corpus,
and the storage ceiling is fully addressed by ADR-0048 on its own.

## Decision

**No message broker — Kafka or otherwise — in v1.** Engagement events continue to be
written directly to the database by `engagement/service.py`, and generation continues
to be driven by `GenerationJob` rows claimed by the batch worker (ADR-0003 §3).

The reasoning is the same shape as ADR-0003 §4's Redis argument, applied to the three
jobs a broker would take on here:

1. **A queue.** We have one: `GenerationJob` in Postgres, claimed with
   `FOR UPDATE SKIP LOCKED` (`worker/__main__.py:125`), with priority ordering
   (ADR-0003 §6) and durability the database already guarantees. The workload it
   serves is bounded by free-tier LLM quota — order tens of jobs per day. A broker
   sized for millions of events per second is not the missing piece.

2. **Write decoupling for engagement.** The premise is that high-frequency engagement
   writes contend with transactional work. Nothing has measured that. Engagement rows
   are ~296 KB total across the entire live database, against 34 MB of content — the
   write path is not remotely the busy one, and `on_conflict_do_nothing` on an
   idempotency key already makes ingest cheap and retry-safe (ADR-0011). Optimizing an
   unmeasured bottleneck is how a project acquires a second database to operate.

3. **Async affinity/telemetry processing.** Real, and genuinely the strongest of the
   three — but ADR-0011's event/state/aggregate split already puts the seam there.
   Aggregates are derived from an append-only event log by a batch job. If that job
   becomes too slow or too coupled, the fix is to change what reads the log, not to
   put a broker in front of writing to it.

The load-bearing constraint is unchanged from ADR-0003: **the binding limit is LLM
generation quota, not throughput.** A swipe is ~50ms and an LLM call is 2–10 seconds.
Kafka makes the fast half faster.

### The cost side, stated plainly

- **A third stateful system to operate**, on a two-person team already responsible for
  a database and a worker — brokers, topics, partitions, consumer groups, offset
  management, rebalancing, dead-letter handling, and the failure modes each of those
  has at 3am.
- **A new class of bug**: at-least-once delivery, consumer lag, out-of-order events,
  and the reprocessing story after a bad deploy. ADR-0011's idempotency key helps, but
  only because it exists — the guarantee is currently "the write either happened or it
  didn't", and a broker replaces that with something weaker.
- **A serverless Kafka tier is metered per message**, which is exactly the failure
  ADR-0003 §4 named for Redis: a per-command meter that an idle polling consumer burns
  through while doing nothing.
- **It violates ADR-0003 §2.** Producing domain events from the request path is not a
  configuration change; removing the broker later would mean unwinding every producer
  call site. This is the "requires a rewrite to undo" category the whole free-tier
  strategy is built to avoid.

## Consequences

**Easier**

- The architecture stays two verticals over one database (CLAUDE.md's read path /
  write path split). A new session does not have to learn a streaming layer to change
  how a swipe is recorded.
- Engagement stays synchronously consistent: a swipe that returns 200 is durably
  recorded, full stop. No "eventually the aggregate catches up" caveat in the UI.

**Harder**

- If engagement volume genuinely does outgrow direct writes, we will be doing that
  migration under load rather than ahead of it. Accepted deliberately: the trigger
  condition is written into "Revisit when" below so the signal is not missed, and the
  event log's existing shape (ADR-0011) is what makes the migration tractable when it
  comes.
- Cross-service fan-out (multiple independent consumers of the same event) stays
  awkward. We have no second consumer today.

**Committed to**

- Anything that looks like a queue keeps living in Postgres until Postgres is measured
  to be the problem — same standard ADR-0003 §4 set for Redis.

## Alternatives considered

**Kafka for engagement telemetry only** (the proposal's narrower option). Lost on the
same measurement point: 296 KB of engagement data is not a decoupling problem. Also
the smaller scope does not shrink the operational cost much — you still run and monitor
a broker, you just use less of it.

**Kafka for the LLM generation pipeline.** Worse than the telemetry version. Generation
is tens of long-running jobs per day gated by a quota governor that deliberately
serializes calls per (key, model) cell (ADR-0040). Streaming buys throughput for a
workload whose entire design goal is *not* to go fast.

**Learn distributed systems on Spoin as the teaching vehicle** — the proposal's stated
"mastery" framing. A legitimate goal, and the reason this rejection is about placement
rather than merit. It lost because a production codebase serving real users is an
expensive classroom: every teaching artifact becomes something the next session has to
read, maintain, and reason around. A standalone sandbox teaches the same material with
no blast radius. Kept out of `docker-compose.yml` for that reason.

**Postgres `LISTEN`/`NOTIFY` as a middle ground.** Not pursued, but genuinely the right
next rung *if* a decoupling need appears: it is additive, needs no new infrastructure,
and unwinds cleanly. Named here so the next person reaching for Kafka checks this
first.

## Revisit when

- **Engagement writes are measured** — not assumed — to be contending with the feed
  read path, or ingest latency shows up in the ~50ms swipe budget (ADR-0010).
- **A second independent consumer of the engagement log exists.** One consumer is a
  batch job; three is a bus, and at three the broker starts paying for itself.
- **The batch aggregate job cannot keep up**, such that users see stale progress for
  long enough to notice. Check whether the fix is a better reader first.
- **Generation stops being quota-bound** (ADR-0003's "traction arrives" trigger). If
  generation throughput is ever limited by our own orchestration rather than by the
  provider's request ceiling, the queue assumptions in §1 above are worth re-reading.
