"""Engagement ingest.

Idempotency and dwell sanitization are covered here because both corrupt *rates*
rather than crashing anything — the kind of bug you discover months later when the
ranker has been quietly wrong the whole time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from slocho.core.config import Settings
from slocho.domain.enums import EngagementKind, SeenState
from slocho.domain.models import CardLike, EngagementEvent, UserCardState
from slocho.engagement.service import EngagementService, IncomingEvent

pytestmark = pytest.mark.asyncio


async def test_duplicate_ids_are_dropped(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Retries must collide, not inflate. `card_quality` is a rate, so a double
    impression makes every score computed from it wrong."""

    service = EngagementService(session, settings)
    event = IncomingEvent(
        id=UUID(int=42), card_id=corpus["cards"][0].id, kind=EngagementKind.IMPRESSION
    )

    first = await service.ingest(corpus["user"].id, [event])
    second = await service.ingest(corpus["user"].id, [event])

    assert first.accepted == 1
    assert second.accepted == 0
    assert second.duplicates == 1

    total = await session.scalar(select(func.count()).select_from(EngagementEvent))
    assert total == 1


async def test_completion_paths_are_recorded_separately(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Both mark a card SEEN; they are very different ranking signals.

    An explicit tap is a deliberate claim of comprehension. Dwell means a tab was
    open. Collapsing them is not recoverable from the log afterwards.
    """

    service = EngagementService(session, settings)
    tapped, dwelt = corpus["cards"][0].id, corpus["cards"][1].id

    await service.ingest(
        corpus["user"].id,
        [
            IncomingEvent(id=uuid4(), card_id=tapped, kind=EngagementKind.EXPLICIT_COMPLETE),
            IncomingEvent(
                id=uuid4(), card_id=dwelt, kind=EngagementKind.DWELL_COMPLETE, dwell_ms=9000
            ),
        ],
    )

    states = {
        row.card_id: row
        for row in (
            await session.execute(
                select(UserCardState).where(UserCardState.user_id == corpus["user"].id)
            )
        ).scalars()
    }

    assert states[tapped].state is SeenState.SEEN
    assert states[dwelt].state is SeenState.SEEN
    assert states[tapped].completed_via is EngagementKind.EXPLICIT_COMPLETE
    assert states[dwelt].completed_via is EngagementKind.DWELL_COMPLETE

    kinds = set((await session.execute(select(EngagementEvent.kind))).scalars().all())
    assert kinds == {EngagementKind.EXPLICIT_COMPLETE, EngagementKind.DWELL_COMPLETE}


async def test_impression_alone_never_marks_seen(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Scrolling past never counts. Expansion is required."""

    service = EngagementService(session, settings)
    card_id = corpus["cards"][0].id

    await service.ingest(
        corpus["user"].id,
        [IncomingEvent(id=uuid4(), card_id=card_id, kind=EngagementKind.IMPRESSION)],
    )

    state = await session.scalar(select(UserCardState).where(UserCardState.card_id == card_id))
    assert state is not None
    assert state.state is SeenState.UNSEEN


async def test_implausible_dwell_is_rejected_at_ingest(
    session: AsyncSession, corpus: dict[str, Any]
) -> None:
    """A tab left open overnight is not a nine-hour engagement, and storing one
    such row skews a card's average permanently."""

    settings = Settings(dwell_max_ms=300_000)
    service = EngagementService(session, settings)

    result = await service.ingest(
        corpus["user"].id,
        [
            IncomingEvent(
                id=uuid4(),
                card_id=corpus["cards"][0].id,
                kind=EngagementKind.DWELL,
                dwell_ms=9 * 60 * 60 * 1000,
            )
        ],
    )

    assert result.accepted == 0
    assert result.rejected == 1


async def test_occurred_at_is_server_assigned(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """Client clocks are wrong, and sometimes deliberately so."""

    lie = datetime(1999, 1, 1, tzinfo=UTC)
    service = EngagementService(session, settings)

    await service.ingest(
        corpus["user"].id,
        [
            IncomingEvent(
                id=uuid4(),
                card_id=corpus["cards"][0].id,
                kind=EngagementKind.IMPRESSION,
                client_occurred_at=lie,
            )
        ],
    )

    event = (await session.execute(select(EngagementEvent))).scalars().one()
    assert event.client_occurred_at == lie, "kept for intra-batch ordering"
    assert event.occurred_at.year >= 2026, "but never used as truth"


async def test_like_and_unlike_round_trip(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    service = EngagementService(session, settings)
    card_id = corpus["cards"][0].id

    await service.ingest(
        corpus["user"].id,
        [IncomingEvent(id=uuid4(), card_id=card_id, kind=EngagementKind.LIKE)],
    )
    assert await session.scalar(select(func.count()).select_from(CardLike)) == 1

    await service.ingest(
        corpus["user"].id,
        [IncomingEvent(id=uuid4(), card_id=card_id, kind=EngagementKind.UNLIKE)],
    )
    assert await session.scalar(select(func.count()).select_from(CardLike)) == 0

    # The log keeps both — mutable state can be undone, the event log cannot.
    assert await session.scalar(select(func.count()).select_from(EngagementEvent)) == 2


async def test_unknown_card_is_rejected_not_fatal(
    session: AsyncSession, corpus: dict[str, Any], settings: Settings
) -> None:
    """One bad row in a buffered batch must not discard the rest of it."""

    service = EngagementService(session, settings)

    result = await service.ingest(
        corpus["user"].id,
        [
            IncomingEvent(id=uuid4(), card_id=uuid4(), kind=EngagementKind.IMPRESSION),
            IncomingEvent(
                id=uuid4(), card_id=corpus["cards"][0].id, kind=EngagementKind.IMPRESSION
            ),
        ],
    )

    assert result.accepted == 1
    assert result.rejected == 1
