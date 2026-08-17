"""Linear ranking, plus epsilon-greedy exploration (ADR-0010).

At this scale a weighted linear score beats a model: debuggable, tunable, and
explainable when the output looks wrong. There is also no training data yet, and
no way to debug a bad learned ranking.

Weights live in config, never here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from spoin.core.config import Settings

#: How quickly `freshness` decays. A card is "new" for about a fortnight.
FRESHNESS_HALF_LIFE = timedelta(days=14)


@dataclass(frozen=True)
class Candidate:
    card_id: UUID
    subtopic_id: UUID
    created_at: datetime
    #: Global engagement RATE across all users — likes per impression, never total
    #: likes. Raw counts make old cards permanently dominant and new cards
    #: permanently invisible.
    card_quality: float
    #: This user's engagement weight for the card's topic.
    topic_affinity: float
    #: Prefers under-consumed subtopics, which is what quietly drives progression
    #: toward the 80% coverage gate rather than letting a user pile up in one
    #: corner of a topic.
    coverage_need: float


def freshness(created_at: datetime, *, now: datetime) -> float:
    """Exponential decay in [0, 1]."""

    age = now - created_at
    if age <= timedelta(0):
        return 1.0
    return float(0.5 ** (age / FRESHNESS_HALF_LIFE))


def score(candidate: Candidate, settings: Settings, *, now: datetime) -> float:
    weights = settings.rank_weights()
    return (
        weights["quality"] * candidate.card_quality
        + weights["affinity"] * candidate.topic_affinity
        + weights["coverage"] * candidate.coverage_need
        + weights["freshness"] * freshness(candidate.created_at, now=now)
    )


def rank(
    candidates: list[Candidate],
    settings: Settings,
    *,
    now: datetime,
    limit: int,
    rng: random.Random | None = None,
) -> list[Candidate]:
    """Top-scoring candidates, with a fixed slice reserved for exploration.

    Serving only top-scored cards creates a cold-start death spiral: new cards get
    no impressions, so accumulate no quality signal, so never rank, so never get
    impressions. A fixed `rank_epsilon` share of every page is drawn at random from
    the remaining eligible candidates so new content can prove itself.

    The exploration slots are **interleaved**, not appended. Bolted onto the end
    they would sit past where most users stop scrolling, which is a slower version
    of never showing them at all.
    """

    if limit <= 0 or not candidates:
        return []

    rng = rng or random.Random()
    ordered = sorted(candidates, key=lambda c: score(c, settings, now=now), reverse=True)

    explore_slots = min(int(limit * settings.rank_epsilon), max(len(ordered) - limit, 0))
    exploit_count = limit - explore_slots

    chosen = ordered[:exploit_count]
    if explore_slots:
        pool = ordered[exploit_count:]
        chosen += rng.sample(pool, min(explore_slots, len(pool)))
        rng.shuffle(chosen)

    return chosen[:limit]


def diversify(candidates: list[Candidate]) -> list[Candidate]:
    """Spread consecutive cards across subtopics.

    Five excellent cards from one subtopic is a worse page than five good cards
    from five subtopics, and that cannot be expressed as a per-card score because
    it depends entirely on what preceded it. So it happens here, after ranking,
    rather than as another weight.
    """

    remaining = list(candidates)
    out: list[Candidate] = []
    last_subtopic: UUID | None = None

    while remaining:
        pick = next(
            (c for c in remaining if c.subtopic_id != last_subtopic),
            remaining[0],  # only one subtopic left; repeating beats dropping cards
        )
        remaining.remove(pick)
        out.append(pick)
        last_subtopic = pick.subtopic_id

    return out
