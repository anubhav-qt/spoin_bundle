"""Session-scoped topic shares, end to end against a real database (ADR-0055).

The share arithmetic itself is covered by `test_session_profile.py`. What is here
is everything that arithmetic depends on being true of the *database*: that the
score accumulates and resets in one atomic upsert, and that the interleave plan
actually changes shape as a result.

The reset in particular is a `CASE` inside `ON CONFLICT DO UPDATE`, so Postgres is
the thing under test — mocking the session would only test that SQLAlchemy builds
the statement, which is not the part that can be wrong.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.core.config import Settings
from spoin.domain.enums import CardStatus, Difficulty, EngagementKind
from spoin.domain.models import (
    Card,
    CardStats,
    FeedPlan,
    Subtopic,
    Topic,
    User,
    UserSessionTopicSignal,
    UserTopic,
)
from spoin.engagement.service import EngagementService, IncomingEvent
from spoin.feed.service import FeedService

pytestmark = pytest.mark.asyncio

CARDS_PER_TOPIC = 30


async def _multi_topic_corpus(session: AsyncSession, topic_count: int) -> dict[str, Any]:
    """A user subscribed to `topic_count` equally-stocked topics.

    Equal stock matters: any difference in the emitted plan then has to come from
    the session signal rather than from one topic simply having more to serve.
    """

    user = User(email=f"{uuid.uuid4()}@test.local", display_name="Test")
    session.add(user)
    await session.flush()

    topics: list[Topic] = []
    cards: dict[uuid.UUID, list[Card]] = {}
    for index in range(topic_count):
        topic = Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name=f"Topic {index}")
        session.add(topic)
        await session.flush()
        session.add(UserTopic(user_id=user.id, topic_id=topic.id, display_name=topic.slug))

        subtopic = Subtopic(
            topic_id=topic.id,
            difficulty=Difficulty.BEGINNER,
            title=f"Subtopic {index}",
            description="…",
            # `ck_subtopic_target_cards_band` caps this at 25; the corpus itself is
            # deliberately larger so a slate never runs dry mid-test.
            target_cards=25,
            min_cards=5,
            position=0,
        )
        session.add(subtopic)
        await session.flush()

        made: list[Card] = []
        for n in range(CARDS_PER_TOPIC):
            card = Card(
                family_id=uuid.uuid4(),
                topic_id=topic.id,
                subtopic_id=subtopic.id,
                difficulty=Difficulty.BEGINNER,
                status=CardStatus.ACTIVE,
                title=f"t{index} card {n}",
                canonical_title=f"t{index} card {n}",
                summary="hook",
                body="body",
            )
            session.add(card)
            made.append(card)
        cards[topic.id] = made
        topics.append(topic)

    await session.flush()
    session.add_all([CardStats(card_id=card.id) for group in cards.values() for card in group])
    await session.flush()
    return {"user": user, "topics": topics, "cards": cards}


async def _engage(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    cards: list[Card],
    kind: EngagementKind,
    *,
    count: int = 1,
    dwell_ms: int | None = None,
) -> None:
    service = EngagementService(session, settings)
    await service.ingest(
        user_id,
        [
            IncomingEvent(id=uuid.uuid4(), card_id=cards[n].id, kind=kind, dwell_ms=dwell_ms)
            for n in range(count)
        ],
    )


async def _signal(session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID) -> float | None:
    return await session.scalar(
        select(UserSessionTopicSignal.score).where(
            UserSessionTopicSignal.user_id == user_id,
            UserSessionTopicSignal.topic_id == topic_id,
        )
    )


async def _plan_counts(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID
) -> Counter[uuid.UUID]:
    """Slot counts from the emitted interleave plan — the actual feed composition,
    not the intermediate share numbers."""

    await FeedService(session, settings).page(user_id)
    plan = await session.scalar(select(FeedPlan).where(FeedPlan.user_id == user_id))
    assert plan is not None
    return Counter(plan.topic_order)


# ------------------------------------------------------------------- accumulate --
async def test_events_accumulate_within_the_session(
    session: AsyncSession, settings: Settings
) -> None:
    corpus = await _multi_topic_corpus(session, 2)
    topic = corpus["topics"][0]
    user_id = corpus["user"].id

    await _engage(session, settings, user_id, corpus["cards"][topic.id], EngagementKind.LIKE)
    after_one = await _signal(session, user_id, topic.id)

    await _engage(session, settings, user_id, corpus["cards"][topic.id][1:], EngagementKind.LIKE)
    after_two = await _signal(session, user_id, topic.id)

    assert after_one == pytest.approx(settings.session_w_like)
    assert after_two == pytest.approx(settings.session_w_like * 2)


async def test_dwell_contributes_in_proportion_to_time(
    session: AsyncSession, settings: Settings
) -> None:
    corpus = await _multi_topic_corpus(session, 2)
    topic = corpus["topics"][0]
    user_id = corpus["user"].id

    await _engage(
        session,
        settings,
        user_id,
        corpus["cards"][topic.id],
        EngagementKind.DWELL,
        dwell_ms=60_000,
    )

    score = await _signal(session, user_id, topic.id)
    assert score == pytest.approx(60 * settings.session_w_dwell_per_second)


async def test_undoing_an_action_leaves_no_residue(
    session: AsyncSession, settings: Settings
) -> None:
    """A mis-tapped like that gets undone must not quietly keep steering the feed."""

    corpus = await _multi_topic_corpus(session, 2)
    topic = corpus["topics"][0]
    user_id = corpus["user"].id
    cards = corpus["cards"][topic.id]

    await _engage(session, settings, user_id, cards, EngagementKind.LIKE)
    await _engage(session, settings, user_id, cards, EngagementKind.UNLIKE)

    assert await _signal(session, user_id, topic.id) == pytest.approx(0.0)


async def test_skipping_pushes_a_topic_negative(session: AsyncSession, settings: Settings) -> None:
    corpus = await _multi_topic_corpus(session, 2)
    topic = corpus["topics"][0]
    user_id = corpus["user"].id

    await _engage(
        session, settings, user_id, corpus["cards"][topic.id], EngagementKind.SKIP, count=3
    )

    score = await _signal(session, user_id, topic.id)
    assert score is not None and score < 0


async def test_impressions_do_not_move_the_profile(
    session: AsyncSession, settings: Settings
) -> None:
    """Being shown a card is not evidence of interest in its topic — otherwise the
    feed would reinforce whatever it happened to serve first."""

    corpus = await _multi_topic_corpus(session, 2)
    topic = corpus["topics"][0]
    user_id = corpus["user"].id

    await _engage(
        session, settings, user_id, corpus["cards"][topic.id], EngagementKind.IMPRESSION, count=5
    )

    assert await _signal(session, user_id, topic.id) is None


# ------------------------------------------------------------------------ reset --
async def test_a_gap_longer_than_the_window_resets_the_score(
    session: AsyncSession, settings: Settings
) -> None:
    """The whole feature: come back tomorrow and the feed is open to anything."""

    corpus = await _multi_topic_corpus(session, 2)
    topic = corpus["topics"][0]
    user_id = corpus["user"].id
    cards = corpus["cards"][topic.id]

    await _engage(session, settings, user_id, cards, EngagementKind.LIKE, count=3)
    assert await _signal(session, user_id, topic.id) == pytest.approx(settings.session_w_like * 3)

    await _age_signal(session, user_id, settings.session_window_seconds + 60)
    await _engage(session, settings, user_id, cards[3:], EngagementKind.LIKE)

    # Not 4x -- the previous session is gone, and this event begins a new one.
    assert await _signal(session, user_id, topic.id) == pytest.approx(settings.session_w_like)


async def test_a_gap_inside_the_window_keeps_the_profile(
    session: AsyncSession, settings: Settings
) -> None:
    corpus = await _multi_topic_corpus(session, 2)
    topic = corpus["topics"][0]
    user_id = corpus["user"].id
    cards = corpus["cards"][topic.id]

    await _engage(session, settings, user_id, cards, EngagementKind.LIKE, count=3)
    await _age_signal(session, user_id, settings.session_window_seconds - 120)
    await _engage(session, settings, user_id, cards[3:], EngagementKind.LIKE)

    assert await _signal(session, user_id, topic.id) == pytest.approx(settings.session_w_like * 4)


async def _age_signal(session: AsyncSession, user_id: uuid.UUID, seconds: int) -> None:
    """Backdate the session row to simulate the user having been away.

    Faster and more precise than waiting, and it exercises the same `CASE` the real
    boundary does.
    """

    await session.execute(
        update(UserSessionTopicSignal)
        .where(UserSessionTopicSignal.user_id == user_id)
        .values(last_event_at=datetime.now(UTC) - timedelta(seconds=seconds))
    )
    await session.flush()


# ------------------------------------------------------------------- feed shares --
async def test_a_fresh_session_is_uniform(session: AsyncSession, settings: Settings) -> None:
    corpus = await _multi_topic_corpus(session, 4)
    counts = await _plan_counts(session, settings, corpus["user"].id)

    assert len(counts) == 4
    assert max(counts.values()) - min(counts.values()) <= 1


async def test_engagement_shifts_the_feed_toward_that_topic(
    session: AsyncSession, settings: Settings
) -> None:
    corpus = await _multi_topic_corpus(session, 4)
    user_id = corpus["user"].id
    favourite = corpus["topics"][0]
    ignored = corpus["topics"][1]

    baseline = await _plan_counts(session, settings, user_id)

    await _engage(
        session,
        settings,
        user_id,
        corpus["cards"][favourite.id],
        EngagementKind.EXPLICIT_COMPLETE,
        count=6,
    )
    shifted = await _plan_counts(session, settings, user_id)

    assert shifted[favourite.id] > baseline[favourite.id]
    assert shifted[ignored.id] < baseline[ignored.id]


async def test_a_dominant_topic_never_takes_more_than_half(
    session: AsyncSession, settings: Settings
) -> None:
    corpus = await _multi_topic_corpus(session, 4)
    user_id = corpus["user"].id
    favourite = corpus["topics"][0]

    for kind in (
        EngagementKind.EXPLICIT_COMPLETE,
        EngagementKind.LIKE,
        EngagementKind.BOOKMARK,
        EngagementKind.SHARE,
    ):
        await _engage(session, settings, user_id, corpus["cards"][favourite.id], kind, count=20)
    for topic in corpus["topics"][1:]:
        await _engage(
            session, settings, user_id, corpus["cards"][topic.id], EngagementKind.SKIP, count=20
        )

    counts = await _plan_counts(session, settings, user_id)
    total = sum(counts.values())
    ceiling = settings.session_share_ceiling * total

    # One slot of slack: the plan is whole slots, so an exact 50% of an odd
    # allocation is not always representable.
    assert counts[favourite.id] <= ceiling + 1


async def test_an_ignored_topic_keeps_its_floor(session: AsyncSession, settings: Settings) -> None:
    """A bad ten minutes must not bury a subscription — the user asked for it."""

    corpus = await _multi_topic_corpus(session, 4)
    user_id = corpus["user"].id
    disliked = corpus["topics"][3]

    for topic in corpus["topics"][:3]:
        await _engage(
            session,
            settings,
            user_id,
            corpus["cards"][topic.id],
            EngagementKind.EXPLICIT_COMPLETE,
            count=20,
        )
    await _engage(
        session, settings, user_id, corpus["cards"][disliked.id], EngagementKind.SKIP, count=20
    )

    counts = await _plan_counts(session, settings, user_id)
    total = sum(counts.values())
    floor = settings.session_share_floor * total

    assert counts[disliked.id] >= floor - 1


async def test_a_stale_profile_reads_as_uniform_before_any_new_event(
    session: AsyncSession, settings: Settings
) -> None:
    """The write-side reset is lazy — it only fires on the next event. Someone who
    returns the next morning and just loads the feed must still get a clean slate.
    """

    corpus = await _multi_topic_corpus(session, 4)
    user_id = corpus["user"].id
    favourite = corpus["topics"][0]

    await _engage(
        session,
        settings,
        user_id,
        corpus["cards"][favourite.id],
        EngagementKind.EXPLICIT_COMPLETE,
        count=10,
    )
    skewed = await _plan_counts(session, settings, user_id)
    assert skewed[favourite.id] > skewed[corpus["topics"][1].id]

    await _age_signal(session, user_id, settings.session_window_seconds + 3600)
    counts = await _plan_counts(session, settings, user_id)

    assert max(counts.values()) - min(counts.values()) <= 1


# -------------------------------------------------------------- plan invalidation --
async def test_the_plan_is_reused_when_the_profile_has_not_moved(
    session: AsyncSession, settings: Settings
) -> None:
    corpus = await _multi_topic_corpus(session, 4)
    user_id = corpus["user"].id

    await _plan_counts(session, settings, user_id)
    first = await session.scalar(select(FeedPlan).where(FeedPlan.user_id == user_id))
    assert first is not None
    fingerprint, order = first.share_fingerprint, list(first.topic_order)

    await _plan_counts(session, settings, user_id)
    second = await session.scalar(select(FeedPlan).where(FeedPlan.user_id == user_id))
    assert second is not None
    assert second.share_fingerprint == fingerprint
    assert list(second.topic_order) == order


async def test_the_plan_rebuilds_once_the_profile_moves(
    session: AsyncSession, settings: Settings
) -> None:
    corpus = await _multi_topic_corpus(session, 4)
    user_id = corpus["user"].id

    await _plan_counts(session, settings, user_id)
    before = await session.scalar(select(FeedPlan).where(FeedPlan.user_id == user_id))
    assert before is not None
    fingerprint = before.share_fingerprint

    await _engage(
        session,
        settings,
        user_id,
        corpus["cards"][corpus["topics"][0].id],
        EngagementKind.EXPLICIT_COMPLETE,
        count=8,
    )
    await _plan_counts(session, settings, user_id)

    after = await session.scalar(select(FeedPlan).where(FeedPlan.user_id == user_id))
    assert after is not None
    assert after.share_fingerprint != fingerprint
