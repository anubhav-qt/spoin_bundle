"""Ranking: linear score, exploration, and post-hoc diversification."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from uuid import uuid4

from spoin.core.config import Settings
from spoin.feed.ranking import Candidate, diversify, freshness, rank, score

NOW = datetime(2026, 8, 15, tzinfo=UTC)


def make_candidate(
    *,
    quality: float = 0.0,
    affinity: float = 1.0,
    coverage: float = 0.0,
    age_days: int = 0,
    subtopic_id: object | None = None,
    archetype: tuple[str, ...] = (),
) -> Candidate:
    return Candidate(
        card_id=uuid4(),
        subtopic_id=subtopic_id or uuid4(),  # type: ignore[arg-type]
        created_at=NOW - timedelta(days=age_days),
        card_quality=quality,
        topic_affinity=affinity,
        coverage_need=coverage,
        archetype=archetype,
    )


def test_freshness_decays() -> None:
    assert freshness(NOW, now=NOW) == 1.0
    assert freshness(NOW - timedelta(days=14), now=NOW) == 0.5
    assert freshness(NOW - timedelta(days=365), now=NOW) < 0.01


def test_higher_quality_scores_higher() -> None:
    settings = Settings()
    low = make_candidate(quality=0.1)
    high = make_candidate(quality=0.9)
    assert score(high, settings, now=NOW) > score(low, settings, now=NOW)


def test_weights_come_from_config() -> None:
    """Ranking weights are config, not code — tuning must not need a deploy."""

    candidate = make_candidate(quality=1.0)
    assert score(candidate, Settings(rank_w_quality=0.0), now=NOW) < score(
        candidate, Settings(rank_w_quality=5.0), now=NOW
    )


def test_exploration_reserves_slots_for_unproven_cards() -> None:
    """Without epsilon, new cards never rank, so never get impressions, so never
    accumulate quality — the cold-start death spiral."""

    proven = [make_candidate(quality=0.9) for _ in range(20)]
    unproven = [make_candidate(quality=0.0) for _ in range(20)]
    settings = Settings(rank_epsilon=0.2)

    chosen = rank(proven + unproven, settings, now=NOW, limit=10, rng=random.Random(0))
    unproven_ids = {c.card_id for c in unproven}

    assert len(chosen) == 10
    assert any(c.card_id in unproven_ids for c in chosen)


def test_zero_epsilon_is_pure_exploitation() -> None:
    proven = [make_candidate(quality=0.9) for _ in range(20)]
    unproven = [make_candidate(quality=0.0) for _ in range(20)]
    settings = Settings(rank_epsilon=0.0)

    chosen = rank(proven + unproven, settings, now=NOW, limit=10, rng=random.Random(0))
    assert {c.card_id for c in chosen} <= {c.card_id for c in proven}


def test_rank_never_exceeds_limit() -> None:
    candidates = [make_candidate() for _ in range(50)]
    assert len(rank(candidates, Settings(), now=NOW, limit=7, rng=random.Random(0))) == 7


def test_diversify_avoids_consecutive_subtopics() -> None:
    """Five excellent cards from one subtopic is a worse page than five good cards
    from five subtopics — and that cannot be a per-card score."""

    first, second = uuid4(), uuid4()
    candidates = [make_candidate(subtopic_id=first) for _ in range(3)] + [
        make_candidate(subtopic_id=second) for _ in range(3)
    ]

    ordered = diversify(candidates)
    subtopics = [c.subtopic_id for c in ordered]

    assert len(ordered) == 6, "diversification must not drop cards"
    assert all(a != b for a, b in pairwise(subtopics))


def test_diversify_tolerates_a_single_subtopic() -> None:
    """Repeating beats dropping when there is nothing to interleave with."""

    only = uuid4()
    candidates = [make_candidate(subtopic_id=only) for _ in range(4)]
    assert len(diversify(candidates)) == 4


def test_diversify_avoids_consecutive_archetypes() -> None:
    """Two diagram cards back to back reads as repetitive even from different
    subtopics — archetype rides along as a secondary spread, distinct
    subtopics per candidate so it isn't the subtopic constraint doing the
    work."""

    candidates = [make_candidate(archetype=("diagram",)) for _ in range(3)] + [
        make_candidate(archetype=("code",)) for _ in range(3)
    ]

    ordered = diversify(candidates)
    archetypes = [c.archetype for c in ordered]

    assert len(ordered) == 6, "diversification must not drop cards"
    assert all(a != b for a, b in pairwise(archetypes))


def test_diversify_falls_back_when_only_one_archetype_remains() -> None:
    """A topic that's run dry on variety (say only 'code' cards left) must
    still serve every card — quantity always wins over variety when they
    conflict, never a starved page."""

    only = uuid4()
    candidates = [make_candidate(subtopic_id=only, archetype=("code",)) for _ in range(4)]
    assert len(diversify(candidates)) == 4
