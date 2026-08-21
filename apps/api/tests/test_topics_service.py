"""TopicsService — the progression rules, now callable without HTTP.

`ensure_unlock_latched` and the coverage gate used to live in a router and be
reachable only through a request. They are the rules that decide whether a user
can sit a quiz, so they are worth pinning directly.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, SeenState
from spoin.domain.models import (
    Card,
    CardStats,
    Subtopic,
    Topic,
    User,
    UserCardState,
    UserTopic,
    UserTopicProgress,
)
from spoin.topics.service import TopicsService, entry_tier_unlock

# ------------------------------------------------------- pure: entry unlock --


def test_beginner_entry_unlocks_nothing_below_it() -> None:
    assert entry_tier_unlock(Difficulty.BEGINNER) == [False, False, False]


def test_intermediate_entry_unlocks_only_beginner() -> None:
    assert entry_tier_unlock(Difficulty.INTERMEDIATE) == [True, False, False]


def test_advanced_entry_unlocks_both_tiers_below() -> None:
    """ADR-0032: strictly below. The entry tier still earns its own quiz
    through the coverage gate, so its slot stays False."""

    assert entry_tier_unlock(Difficulty.ADVANCED) == [True, True, False]


# ------------------------------------------------------------ DB-backed --


async def _topic_with_cards(
    session: AsyncSession, *, subtopics: list[int]
) -> tuple[uuid.UUID, uuid.UUID, list[Card]]:
    """One user subscribed to one topic whose beginner tier has `subtopics`
    subtopics, each with the given number of active cards."""

    user = User(email=f"{uuid.uuid4()}@test.local", display_name="Test")
    topic = Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name="Coverage")
    session.add_all([user, topic])
    await session.flush()

    session.add(UserTopic(user_id=user.id, topic_id=topic.id, display_name="Coverage"))
    session.add(
        UserTopicProgress(
            user_id=user.id,
            topic_id=topic.id,
            current_difficulty=Difficulty.BEGINNER,
            tier_unlocked=entry_tier_unlock(Difficulty.BEGINNER),
        )
    )

    cards: list[Card] = []
    for index, count in enumerate(subtopics):
        subtopic = Subtopic(
            topic_id=topic.id,
            difficulty=Difficulty.BEGINNER,
            title=f"Subtopic {index}",
            description="…",
            target_cards=10,
            min_cards=5,
            position=index,
        )
        session.add(subtopic)
        await session.flush()
        for n in range(count):
            card = Card(
                family_id=uuid.uuid4(),
                topic_id=topic.id,
                subtopic_id=subtopic.id,
                difficulty=Difficulty.BEGINNER,
                status=CardStatus.ACTIVE,
                title=f"s{index} card {n}",
                canonical_title=f"s{index} card {n}",
                summary="hook",
                body="body",
            )
            session.add(card)
            cards.append(card)
    await session.flush()
    session.add_all([CardStats(card_id=c.id) for c in cards])
    await session.flush()
    return user.id, topic.id, cards


async def _mark_seen(session: AsyncSession, user_id: uuid.UUID, cards: list[Card]) -> None:
    for card in cards:
        session.add(
            UserCardState(
                user_id=user_id,
                card_id=card.id,
                # Denormalised off the card and NOT NULL — see the model.
                topic_id=card.topic_id,
                subtopic_id=card.subtopic_id,
                state=SeenState.SEEN,
            )
        )
    await session.flush()


@pytest.fixture
def service_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


async def test_coverage_is_governed_by_the_weakest_subtopic(
    session: AsyncSession, service_settings: Settings
) -> None:
    """The gate is "80% of EVERY subtopic", so one fully-read subtopic beside
    an untouched one must not average out to a pass."""

    user_id, topic_id, cards = await _topic_with_cards(session, subtopics=[10, 10])
    await _mark_seen(session, user_id, cards[:10])  # first subtopic only

    _tier, coverage, unlocked, _mastered = await TopicsService(
        session, service_settings
    ).progress_snapshot(user_id, topic_id)

    assert coverage == 0.0
    assert unlocked is False


async def test_reaching_the_gate_unlocks(session: AsyncSession, service_settings: Settings) -> None:
    user_id, topic_id, cards = await _topic_with_cards(session, subtopics=[10])
    await _mark_seen(session, user_id, cards[:8])  # exactly 80%

    _tier, coverage, unlocked, _mastered = await TopicsService(
        session, service_settings
    ).progress_snapshot(user_id, topic_id)

    assert coverage == pytest.approx(0.8)
    assert unlocked is True


async def test_snapshot_does_not_write_the_latch(
    session: AsyncSession, service_settings: Settings
) -> None:
    """`progress_snapshot` exists precisely so a read-only caller can ask
    without causing a write."""

    user_id, topic_id, cards = await _topic_with_cards(session, subtopics=[10])
    await _mark_seen(session, user_id, cards[:8])
    service = TopicsService(session, service_settings)

    await service.progress_snapshot(user_id, topic_id)

    progress = await session.get(UserTopicProgress, (user_id, topic_id))
    assert progress is not None
    assert progress.tier_unlocked[Difficulty.BEGINNER.rank] is False


async def test_unlock_latches_and_survives_new_cards_landing(
    session: AsyncSession, service_settings: Settings
) -> None:
    """The reason the latch exists: background generation must never revoke
    progress a user already earned. 8/10 (unlocked) becoming 8/20 must not
    re-lock the tier."""

    user_id, topic_id, cards = await _topic_with_cards(session, subtopics=[10])
    await _mark_seen(session, user_id, cards[:8])
    service = TopicsService(session, service_settings)

    _progress, _tier, _coverage, unlocked, _mastered = await service.ensure_unlock_latched(
        user_id, topic_id
    )
    assert unlocked is True

    subtopic_id = cards[0].subtopic_id
    for n in range(10):
        session.add(
            Card(
                family_id=uuid.uuid4(),
                topic_id=topic_id,
                subtopic_id=subtopic_id,
                difficulty=Difficulty.BEGINNER,
                status=CardStatus.ACTIVE,
                title=f"late card {n}",
                canonical_title=f"late card {n}",
                summary="hook",
                body="body",
            )
        )
    await session.flush()

    _p, _t, coverage, still_unlocked, _m = await service.ensure_unlock_latched(user_id, topic_id)
    assert coverage == pytest.approx(0.4)
    assert still_unlocked is True, "the latch must not be recomputed away"
