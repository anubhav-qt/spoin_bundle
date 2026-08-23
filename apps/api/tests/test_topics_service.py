"""TopicsService — the progression rules, now callable without HTTP.

`ensure_unlock_latched` and the coverage gate used to live in a router and be
reachable only through a request. They are the rules that decide whether a user
can sit a quiz, so they are worth pinning directly.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, SeenState
from spoin.domain.models import (
    Card,
    CardStats,
    GenerationJob,
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


# ------------------------------------------------------------ set_color -----


async def test_set_color_stores_a_chosen_hue(
    session: AsyncSession, service_settings: Settings
) -> None:
    user_id, topic_id, _cards = await _topic_with_cards(session, subtopics=[])
    service = TopicsService(session, service_settings)

    out = await service.set_color(user_id, topic_id, 200)

    assert out.accent_hue == 200
    user_topic = await session.scalar(
        select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
    )
    assert user_topic is not None
    assert user_topic.accent_hue == 200


async def test_set_color_none_resets_to_the_deterministic_default(
    session: AsyncSession, service_settings: Settings
) -> None:
    """`hue=None` clears any stored value -- the client, not the row, owns the
    default (ADR-0034)."""

    user_id, topic_id, _cards = await _topic_with_cards(session, subtopics=[])
    service = TopicsService(session, service_settings)
    await service.set_color(user_id, topic_id, 200)

    out = await service.set_color(user_id, topic_id, None)

    assert out.accent_hue is None


async def test_set_color_sentinel_opts_out_of_topic_color(
    session: AsyncSession, service_settings: Settings
) -> None:
    """ADR-0051: `-1` is stored as-is, a third state alongside a real hue and
    the null default -- the sentinel is purely a client-side convention, the
    service has no special-casing for it."""

    user_id, topic_id, _cards = await _topic_with_cards(session, subtopics=[])
    service = TopicsService(session, service_settings)

    out = await service.set_color(user_id, topic_id, -1)

    assert out.accent_hue == -1


# --------------------------------------------- live-coverage threshold (ADR-0053) --


async def test_list_all_hides_unfollowed_topics_below_the_live_threshold(
    session: AsyncSession, service_settings: Settings
) -> None:
    """`_topic_with_cards` fixes `min_cards=5` per subtopic. One covered
    subtopic out of two is exactly the 0.5 boundary -- live. Zero out of two
    is not."""

    _owner_id, live_topic_id, _cards = await _topic_with_cards(session, subtopics=[5, 0])
    _other_id, not_live_topic_id, _cards2 = await _topic_with_cards(session, subtopics=[0, 0])
    viewer_id, own_topic_id, _cards3 = await _topic_with_cards(session, subtopics=[])

    out = await TopicsService(session, service_settings).list_all(viewer_id)
    ids = {t.topic_id for t in out}

    assert live_topic_id in ids
    assert not_live_topic_id not in ids
    # Followed (it's the viewer's own topic) bypasses the filter entirely,
    # even with zero subtopics -- otherwise a reader would lose their own
    # just-requested topic from "Topics" while it's still generating.
    assert own_topic_id in ids


async def test_discover_applies_the_same_live_filter(
    session: AsyncSession, service_settings: Settings
) -> None:
    _owner_id, live_topic_id, _cards = await _topic_with_cards(session, subtopics=[5, 0])
    _other_id, not_live_topic_id, _cards2 = await _topic_with_cards(session, subtopics=[0, 0])
    viewer_id, _own_topic_id, _cards3 = await _topic_with_cards(session, subtopics=[])

    out = await TopicsService(session, service_settings).discover(viewer_id)
    ids = {t.topic_id for t in out}

    assert live_topic_id in ids
    assert not_live_topic_id not in ids


async def test_generation_progress_reports_topic_live_once_threshold_crossed(
    session: AsyncSession, service_settings: Settings
) -> None:
    _owner_id, topic_id, _cards = await _topic_with_cards(session, subtopics=[5, 0])
    session.add(
        GenerationJob(
            topic_id=topic_id, status="running", progress={"stage": "cards", "subtopics": []}
        )
    )
    await session.flush()

    out = await TopicsService(session, service_settings).generation_progress(topic_id)

    assert out.topic_live is True


async def test_generation_progress_reports_topic_not_live_below_threshold(
    session: AsyncSession, service_settings: Settings
) -> None:
    _owner_id, topic_id, _cards = await _topic_with_cards(session, subtopics=[0, 0])
    session.add(
        GenerationJob(
            topic_id=topic_id, status="running", progress={"stage": "cards", "subtopics": []}
        )
    )
    await session.flush()

    out = await TopicsService(session, service_settings).generation_progress(topic_id)

    assert out.topic_live is False


# ------------------------------------------------- cancel_generation --


async def _pending_custom_request(
    session: AsyncSession, *, job_status: str = "pending"
) -> tuple[uuid.UUID, uuid.UUID]:
    """A user's own custom-topic request, still in the state right after
    `request_topic` created it: subscribed, no cards, one job."""

    user = User(email=f"{uuid.uuid4()}@test.local", display_name="Test")
    topic = Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name="Requested Topic")
    session.add_all([user, topic])
    await session.flush()

    session.add(
        UserTopic(user_id=user.id, topic_id=topic.id, display_name="Requested Topic", is_custom=True)
    )
    session.add(
        UserTopicProgress(
            user_id=user.id,
            topic_id=topic.id,
            current_difficulty=Difficulty.BEGINNER,
            tier_unlocked=entry_tier_unlock(Difficulty.BEGINNER),
        )
    )
    session.add(GenerationJob(topic_id=topic.id, status=job_status))
    await session.flush()
    return user.id, topic.id


async def test_cancel_generation_removes_job_subscription_and_orphaned_topic(
    session: AsyncSession, service_settings: Settings
) -> None:
    user_id, topic_id = await _pending_custom_request(session)

    await TopicsService(session, service_settings).cancel_generation(user_id, topic_id)

    assert (
        await session.scalar(select(GenerationJob).where(GenerationJob.topic_id == topic_id))
    ) is None
    assert (
        await session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
    ) is None
    assert await session.get(Topic, topic_id) is None


async def test_cancel_generation_refuses_once_running(
    session: AsyncSession, service_settings: Settings
) -> None:
    """A worker already claimed it -- real quota may be spent, so this
    refuses rather than racing the worker's own writes."""

    user_id, topic_id = await _pending_custom_request(session, job_status="running")

    with pytest.raises(HTTPException) as exc_info:
        await TopicsService(session, service_settings).cancel_generation(user_id, topic_id)
    assert exc_info.value.status_code == 409

    # Nothing was touched -- the job, subscription, and topic all survive.
    assert (
        await session.scalar(select(GenerationJob).where(GenerationJob.topic_id == topic_id))
    ) is not None
    assert await session.get(Topic, topic_id) is not None


async def test_cancel_generation_keeps_topic_when_other_followers_remain(
    session: AsyncSession, service_settings: Settings
) -> None:
    user_id, topic_id = await _pending_custom_request(session)

    other = User(email=f"{uuid.uuid4()}@test.local", display_name="Other")
    session.add(other)
    await session.flush()
    session.add(UserTopic(user_id=other.id, topic_id=topic_id, display_name="Shared"))
    await session.flush()

    await TopicsService(session, service_settings).cancel_generation(user_id, topic_id)

    assert await session.get(Topic, topic_id) is not None
    assert (
        await session.scalar(
            select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
        )
    ) is None


async def test_cancel_generation_404s_for_a_non_requester(
    session: AsyncSession, service_settings: Settings
) -> None:
    _owner_id, topic_id = await _pending_custom_request(session)
    stranger = User(email=f"{uuid.uuid4()}@test.local", display_name="Stranger")
    session.add(stranger)
    await session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await TopicsService(session, service_settings).cancel_generation(stranger.id, topic_id)
    assert exc_info.value.status_code == 404
