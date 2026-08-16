"""Feed endpoints.

**No LLM call may appear in this module or anything it reaches.** Hard rule 1.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from slocho.api.deps import SessionDep, SettingsDep, UserDep
from slocho.api.schemas import CardOut, FeedOut
from slocho.domain.models import Card, Subtopic
from slocho.feed.service import FeedService

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("", response_model=FeedOut)
async def get_feed(
    session: SessionDep,
    settings: SettingsDep,
    user_id: UserDep,
    topics: list[UUID] | None = Query(default=None, description="Filter to these topics"),
    position: int | None = Query(default=None, description="Position into the interleave plan"),
) -> FeedOut:
    service = FeedService(session, settings)
    page = await service.page(user_id, topic_filter=topics, position=position)

    cards: list[CardOut] = []
    if page.card_ids:
        # Joined rather than fetched separately: the client groups cards under
        # station headers and needs the subtopic's title to label them. A second
        # round trip for that would sit on the one path with a <100ms budget.
        rows = (
            await session.execute(
                select(Card, Subtopic.title)
                .join(Subtopic, Subtopic.id == Card.subtopic_id)
                .where(Card.id.in_(page.card_ids))
            )
        ).all()

        # Preserve the ranked order — SELECT ... IN does not.
        by_id = {row[0].id: row for row in rows}
        cards = [
            CardOut(
                id=card.id,
                topic_id=card.topic_id,
                subtopic_id=card.subtopic_id,
                subtopic_title=subtopic_title,
                difficulty=card.difficulty,
                title=card.title,
                summary=card.summary,
                body=card.body,
                archetype=card.archetype,
                is_hero=card.is_hero,
                created_at=card.created_at,
            )
            for card_id in page.card_ids
            if (row := by_id.get(card_id)) is not None
            for card, subtopic_title in [row]
        ]

    # Starved slots would enqueue coalesced fill jobs here, keyed on subtopic_id
    # (ADR-0007's amendment to ADR-0006). Not wired up until the worker's fill job
    # exists — enqueueing into a queue nothing drains would just accumulate rows.

    await session.commit()

    return FeedOut(
        cards=cards,
        next_position=page.next_position,
        degraded=page.degraded,
        exhausted=page.exhausted,
    )
