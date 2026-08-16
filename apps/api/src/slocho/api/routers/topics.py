"""Topic subscriptions and progress."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from slocho.api.deps import SessionDep, UserDep
from slocho.api.schemas import (
    ProgressOut,
    TopicDiscoverOut,
    TopicOut,
    TopicStatsOut,
)
from slocho.domain.enums import Difficulty, EngagementKind, SeenState
from slocho.domain.models import (
    Card,
    CardBookmark,
    CardLike,
    EngagementEvent,
    Subtopic,
    Topic,
    UserCardState,
    UserTopic,
    UserTopicProgress,
)

#: Notes/shares have no mutable-state table (ADR-0015) — these are the only two
#: kinds `/topics/{id}/stats` aggregates from the raw event log rather than a
#: current-state count.
_STATS_EVENT_KINDS = (EngagementKind.NOTE, EngagementKind.SHARE)

router = APIRouter(prefix="/topics", tags=["topics"])

#: The coverage gate (ADR-0009). Relative rather than absolute so it self-adjusts
#: to whatever the corpus actually holds — a thin subtopic cannot strand a user at
#: an unreachable bar.
COVERAGE_GATE = 0.80


@router.get("", response_model=list[TopicOut])
async def list_topics(session: SessionDep, user_id: UserDep) -> list[TopicOut]:
    rows = (
        await session.execute(
            select(UserTopic, Topic, UserTopicProgress.current_difficulty)
            .join(Topic, Topic.id == UserTopic.topic_id)
            .outerjoin(
                UserTopicProgress,
                (UserTopicProgress.user_id == UserTopic.user_id)
                & (UserTopicProgress.topic_id == UserTopic.topic_id),
            )
            .where(UserTopic.user_id == user_id)
            .order_by(UserTopic.created_at)
        )
    ).all()

    return [
        TopicOut(
            id=topic.id,
            # The user's own label, never the canonical name.
            display_name=user_topic.display_name,
            slug=topic.slug,
            is_custom=user_topic.is_custom,
            current_difficulty=tier or Difficulty.BEGINNER,
        )
        for user_topic, topic, tier in rows
    ]


@router.get("/discover", response_model=list[TopicDiscoverOut])
async def discover_topics(
    session: SessionDep, user_id: UserDep, mode: str = "popular"
) -> list[TopicDiscoverOut]:
    """Top 5 topics the user doesn't already follow, ranked by subscriber_count.

    `mode` is accepted but `for_you` runs the identical query for now — there is
    no signal yet to personalize from for topics a user hasn't subscribed to
    (see ADR-0015, task 0003). The parameter exists so the frontend toggle and
    this route don't need to change shape once that work lands.
    """
    del mode  # Both modes share one query today; kept as a real branch point.

    followed = select(UserTopic.topic_id).where(UserTopic.user_id == user_id)
    rows = (
        await session.execute(
            select(Topic)
            .where(Topic.id.not_in(followed))
            .order_by(Topic.subscriber_count.desc())
            .limit(5)
        )
    ).scalars().all()

    return [
        TopicDiscoverOut(
            topic_id=topic.id,
            display_name=topic.canonical_name,
            subscriber_count=topic.subscriber_count,
        )
        for topic in rows
    ]


@router.post("/{topic_id}/subscribe", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def subscribe_topic(topic_id: UUID, session: SessionDep, user_id: UserDep) -> TopicOut:
    topic = await session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown topic")

    existing = await session.scalar(
        select(UserTopic).where(UserTopic.user_id == user_id, UserTopic.topic_id == topic_id)
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Already subscribed")

    # No rename UI exists yet (ADR-0004's personal-label split), so the label
    # starts as the canonical name — same default seed.py uses.
    user_topic = UserTopic(
        user_id=user_id, topic_id=topic_id, display_name=topic.canonical_name, is_custom=False
    )
    session.add(user_topic)
    topic.subscriber_count += 1
    session.add(UserTopicProgress(user_id=user_id, topic_id=topic_id))
    await session.commit()

    return TopicOut(
        id=topic.id,
        display_name=user_topic.display_name,
        slug=topic.slug,
        is_custom=False,
        current_difficulty=Difficulty.BEGINNER,
    )


@router.get("/{topic_id}/stats", response_model=TopicStatsOut)
async def get_topic_stats(topic_id: UUID, session: SessionDep, user_id: UserDep) -> TopicStatsOut:
    tier, coverage, unlocked, mastered = await _progress_snapshot(session, user_id, topic_id)

    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id
        )
    )

    likes = await session.scalar(
        select(func.count())
        .select_from(CardLike)
        .join(Card, Card.id == CardLike.card_id)
        .where(CardLike.user_id == user_id, Card.topic_id == topic_id)
    )
    saves = await session.scalar(
        select(func.count())
        .select_from(CardBookmark)
        .join(Card, Card.id == CardBookmark.card_id)
        .where(CardBookmark.user_id == user_id, Card.topic_id == topic_id)
    )

    event_rows = (
        await session.execute(
            select(EngagementEvent.kind, func.count())
            .where(
                EngagementEvent.user_id == user_id,
                EngagementEvent.topic_id == topic_id,
                EngagementEvent.kind.in_(_STATS_EVENT_KINDS),
            )
            .group_by(EngagementEvent.kind)
        )
    ).all()
    event_counts = {kind: count for kind, count in event_rows}

    return TopicStatsOut(
        topic_id=topic_id,
        current_difficulty=tier,
        coverage=coverage,
        quiz_unlocked=unlocked,
        mastered=mastered,
        tier_quiz_passed=list(progress.tier_quiz_passed) if progress else [False] * 3,
        likes=likes or 0,
        saves=saves or 0,
        notes=event_counts.get(EngagementKind.NOTE, 0),
        shares=event_counts.get(EngagementKind.SHARE, 0),
    )


@router.get("/{topic_id}/progress", response_model=ProgressOut)
async def get_progress(topic_id: UUID, session: SessionDep, user_id: UserDep) -> ProgressOut:
    tier, coverage, unlocked, mastered = await _progress_snapshot(session, user_id, topic_id)

    # The latch. Once unlocked, it stays unlocked: recomputing would let background
    # generation revoke earned progress, dropping a user from 8/10 (80%) to 8/20
    # (40%) the moment ten more cards land.
    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id,
            UserTopicProgress.topic_id == topic_id,
        )
    )
    already_unlocked = bool(progress and progress.tier_unlocked[tier.rank])
    if unlocked and progress is not None and not already_unlocked:
        latched = list(progress.tier_unlocked)
        latched[tier.rank] = True
        progress.tier_unlocked = latched
        await session.commit()

    return ProgressOut(
        topic_id=topic_id,
        current_difficulty=tier,
        coverage=coverage,
        quiz_unlocked=unlocked,
        tier_quiz_passed=list(progress.tier_quiz_passed) if progress else [False] * 3,
        mastered=mastered,
    )


async def _progress_snapshot(
    session: SessionDep, user_id: UUID, topic_id: UUID
) -> tuple[Difficulty, float, bool, bool]:
    """Read-only version of `get_progress`'s lookup: tier, coverage, unlocked, mastered.

    Split out so a future read-only caller (a stats/insights view, say) can
    reuse this without also triggering `get_progress`'s latch write.
    """

    progress = await session.scalar(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id,
            UserTopicProgress.topic_id == topic_id,
        )
    )
    tier = progress.current_difficulty if progress else Difficulty.BEGINNER
    coverage = await _tier_coverage(session, user_id, topic_id, tier)
    already_unlocked = bool(progress and progress.tier_unlocked[tier.rank])
    unlocked = already_unlocked or coverage >= COVERAGE_GATE
    mastered = bool(progress and progress.mastered_at is not None)
    return tier, coverage, unlocked, mastered


async def _tier_coverage(
    session: SessionDep, user_id: UUID, topic_id: UUID, tier: Difficulty
) -> float:
    """Coverage of the **weakest** subtopic in the tier.

    The gate is "80% of the cards in EVERY subtopic", so the thinnest one governs.
    Averaging across subtopics would let a user coast on one well-read subtopic
    while never opening another.
    """

    rows = (
        await session.execute(
            select(
                Subtopic.id,
                func.count(Card.id),
                func.count(UserCardState.card_id).filter(UserCardState.state == SeenState.SEEN),
            )
            .select_from(Subtopic)
            .outerjoin(Card, (Card.subtopic_id == Subtopic.id))
            .outerjoin(
                UserCardState,
                (UserCardState.card_id == Card.id) & (UserCardState.user_id == user_id),
            )
            .where(Subtopic.topic_id == topic_id, Subtopic.difficulty == tier)
            .group_by(Subtopic.id)
        )
    ).all()

    ratios = [seen / total for _, total, seen in rows if total]
    return min(ratios) if ratios else 0.0
