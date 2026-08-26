"""ProfileService.get_today_progress -- ADR-0062's two claims:

1. distinct cards, not event rows (a dwell_complete + explicit_complete on
   the same card is one card read).
2. "today" is the caller's local day, computed from a client-supplied UTC
   offset, not UTC.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from spoin.domain.enums import CardStatus, Difficulty, EngagementKind
from spoin.domain.models import Card, EngagementEvent, Subtopic, Topic, User
from spoin.profile.service import ProfileService


async def _user_with_card(
    session: AsyncSession, *, daily_card_goal: int = 10
) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"{uuid.uuid4()}@test.local", display_name="Test", daily_card_goal=daily_card_goal
    )
    topic = Topic(slug=f"t-{uuid.uuid4().hex[:8]}", canonical_name="Coverage")
    session.add_all([user, topic])
    await session.flush()

    subtopic = Subtopic(
        topic_id=topic.id,
        difficulty=Difficulty.BEGINNER,
        title="Subtopic",
        description="…",
        target_cards=10,
        min_cards=5,
        position=0,
    )
    session.add(subtopic)
    await session.flush()

    card = Card(
        family_id=uuid.uuid4(),
        topic_id=topic.id,
        subtopic_id=subtopic.id,
        difficulty=Difficulty.BEGINNER,
        status=CardStatus.ACTIVE,
        title="Card",
        canonical_title="Card",
        summary="hook",
        body="body",
    )
    session.add(card)
    await session.flush()

    return user.id, card.id


def _event(
    *, user_id: uuid.UUID, card_id: uuid.UUID, kind: EngagementKind, occurred_at: datetime.datetime
) -> EngagementEvent:
    return EngagementEvent(
        id=uuid.uuid4(),
        user_id=user_id,
        card_id=card_id,
        topic_id=uuid.uuid4(),
        subtopic_id=uuid.uuid4(),
        kind=kind,
        occurred_at=occurred_at,
    )


async def test_two_completion_events_on_one_card_count_once(session: AsyncSession) -> None:
    """The bug ADR-0060 fixes: dwell_complete then explicit_complete on the
    same card used to count as two cards read."""

    user_id, card_id = await _user_with_card(session)
    now = datetime.datetime.now(datetime.UTC)
    session.add_all(
        [
            _event(
                user_id=user_id,
                card_id=card_id,
                kind=EngagementKind.DWELL_COMPLETE,
                occurred_at=now,
            ),
            _event(
                user_id=user_id,
                card_id=card_id,
                kind=EngagementKind.EXPLICIT_COMPLETE,
                occurred_at=now,
            ),
        ]
    )
    await session.flush()

    result = await ProfileService(session).get_today_progress(user_id, tz_offset_minutes=0)

    assert result.cards_read == 1


def _local_day_start_utc(offset_minutes: int) -> datetime.datetime:
    """Mirrors ProfileService.get_today_progress's own boundary math, so the
    test can place events exactly on either side of it without mocking
    `datetime.now`."""

    offset = datetime.timedelta(minutes=offset_minutes)
    local_now = datetime.datetime.now(datetime.UTC) + offset
    local_midnight = datetime.datetime(
        local_now.year, local_now.month, local_now.day, tzinfo=datetime.UTC
    )
    return local_midnight - offset


async def test_today_progress_boundary_moves_with_the_offset(session: AsyncSession) -> None:
    """An event placed one minute before UTC's local-day start but one
    minute after IST's (or vice versa, depending on the moment the suite
    runs) proves the boundary genuinely shifts with `tz_offset_minutes`
    rather than always meaning UTC midnight."""

    user_id, card_id = await _user_with_card(session)
    ist_offset = 5 * 60 + 30

    utc_start = _local_day_start_utc(0)
    ist_start = _local_day_start_utc(ist_offset)

    # One minute before whichever boundary is LATER -- guaranteed to fall
    # after the earlier boundary and before the later one, so it's "today"
    # under exactly one of the two offsets.
    later_boundary = max(utc_start, ist_start)
    probe_time = later_boundary - datetime.timedelta(minutes=1)
    session.add(
        _event(
            user_id=user_id,
            card_id=card_id,
            kind=EngagementKind.DWELL_COMPLETE,
            occurred_at=probe_time,
        )
    )
    await session.flush()

    service = ProfileService(session)
    result_utc = await service.get_today_progress(user_id, tz_offset_minutes=0)
    result_ist = await service.get_today_progress(user_id, tz_offset_minutes=ist_offset)

    counted_as_today = {result_utc.cards_read, result_ist.cards_read}
    assert counted_as_today == {0, 1}, (
        "the probe event must count as today under exactly one offset"
    )


async def test_daily_goal_rides_along(session: AsyncSession) -> None:
    user_id, _card_id = await _user_with_card(session, daily_card_goal=25)

    result = await ProfileService(session).get_today_progress(user_id, tz_offset_minutes=0)

    assert result.goal == 25
    assert result.cards_read == 0
