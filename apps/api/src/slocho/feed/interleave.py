"""The cross-topic interleave plan (ADR-0010).

Weighted round-robin with deficit counters — the algorithm packet schedulers use
for weighted fair queuing. Deterministic, and a topic with 2x the affinity gets 2x
the slots **spread evenly** rather than clumped into a run.

This is the cheap, volatile half of the pagination design. The expensive half (the
per-topic ranked slate) is cached because it is rarely invalidated; this half is
regenerated freely on filter change, affinity shift, or slate refill, because
recomputing it requires no ranking at all.
"""

from __future__ import annotations

from uuid import UUID


def build_plan(affinities: dict[UUID, float], size: int, run_length: int = 1) -> list[UUID]:
    """`size` topic slots, allocated in proportion to affinity.

    `run_length` is how many consecutive slots a topic wins at a time. At 1 this
    is exactly ADR-0010's "spread evenly rather than clumped". Above 1 the *share*
    each topic receives is unchanged — only the granularity of alternation is —
    which is what lets the client group the feed under per-topic headings without
    a heading appearing before every single card.

    Returns an empty plan for no topics rather than raising: a user with no
    subscriptions is an ordinary state, not an error.
    """

    topics = [topic for topic, weight in affinities.items() if weight > 0]
    if not topics or size <= 0:
        return []

    run = max(1, run_length)

    # Deterministic ordering, so the same inputs always produce the same plan and
    # a surprising feed can actually be reproduced from a bug report.
    topics.sort(key=lambda topic: (-affinities[topic], str(topic)))

    total_weight = sum(affinities[topic] for topic in topics)
    deficits = dict.fromkeys(topics, 0.0)
    plan: list[UUID] = []

    # Deficit round-robin over *runs* rather than single slots. Awarding a whole
    # run at once and charging the winner for all of it keeps the long-run share
    # proportional to affinity.
    while len(plan) < size:
        for topic in topics:
            deficits[topic] += run * affinities[topic] / total_weight
        winner = max(topics, key=lambda topic: (deficits[topic], -topics.index(topic)))
        deficits[winner] -= float(run)
        plan.extend([winner] * min(run, size - len(plan)))

    return plan


def filter_key(topic_ids: list[UUID] | None) -> str:
    """A stable key for the active topic filter.

    A filter change regenerates the plan and leaves every slate intact — which is
    why a user can filter to one topic, read, unfilter, and resume exactly where
    they were in every other topic.
    """

    if not topic_ids:
        return ""
    return ",".join(sorted(str(topic_id) for topic_id in topic_ids))
