"""Feed endpoints and liked-card collection.

**No LLM call may appear in this module or anything it reaches.** Hard rule 1.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from spoin.api.deps import SessionDep, SettingsDep, UserDep
from spoin.api.schemas import CardOut, FeedOut, LikedCardOut, SavedCardOut
from spoin.domain.models import Card, CardBookmark, CardLike, Subtopic, Topic, UserTopic
from spoin.feed.service import FeedService
from spoin.notes.service import NotesService

router = APIRouter(prefix="/feed", tags=["feed"])

# A minimal second router for card-level operations so they live at /cards
# rather than /feed/cards — keeps the URL hierarchy tidy without a new file.
cards_router = APIRouter(prefix="/cards", tags=["feed"])


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
        # A second, small query rather than a join into the ranked query above —
        # notes are private, per-user state (CardNote's own contract: "never fed
        # to ranking"), so keeping it out of the candidate/ranking query is
        # deliberate, not an oversight.
        notes_by_card = await NotesService(session).get_for_cards(user_id, list(page.card_ids))
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
                visual_id=card.visual_id,
                visual_slots=card.visual_slots,
                created_at=card.created_at,
                note=notes_by_card.get(card_id),
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


@cards_router.get("/liked", response_model=list[LikedCardOut])
async def get_liked_cards(
    session: SessionDep,
    user_id: UserDep,
    topic_id: UUID | None = Query(default=None, description="Filter to one topic"),
    sort: Literal["recent", "oldest", "topic", "difficulty"] = Query(
        default="recent", description="Sort order"
    ),
) -> list[LikedCardOut]:
    """Every card this user has liked, with enough context to render inline.

    Pure data retrieval — no LLM, no generation, no ranking computation.
    Returns in the requested sort order so the client never has to re-sort a
    large collection in JS.

    Notes are included via a second query (same deliberate separation as the
    feed endpoint — they're private state, never mixed into the card query).
    """

    display_name = func.coalesce(UserTopic.display_name, Topic.canonical_name)

    stmt = (
        select(CardLike.created_at, Card, Subtopic.title, display_name)
        .join(Card, Card.id == CardLike.card_id)
        .join(Subtopic, Subtopic.id == Card.subtopic_id)
        .join(Topic, Topic.id == Card.topic_id)
        .outerjoin(
            UserTopic,
            (UserTopic.user_id == CardLike.user_id) & (UserTopic.topic_id == Card.topic_id),
        )
        .where(CardLike.user_id == user_id)
    )

    if topic_id is not None:
        stmt = stmt.where(Card.topic_id == topic_id)

    if sort == "recent":
        stmt = stmt.order_by(CardLike.created_at.desc())
    elif sort == "oldest":
        stmt = stmt.order_by(CardLike.created_at.asc())
    elif sort == "topic":
        stmt = stmt.order_by(display_name.asc(), CardLike.created_at.desc())
    elif sort == "difficulty":
        stmt = stmt.order_by(Card.difficulty.asc(), CardLike.created_at.desc())

    rows = (await session.execute(stmt)).all()

    if not rows:
        return []

    card_ids = [card.id for _, card, _, _ in rows]
    notes_by_card = await NotesService(session).get_for_cards(user_id, card_ids)

    return [
        LikedCardOut(
            card=CardOut(
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
                visual_id=card.visual_id,
                visual_slots=card.visual_slots,
                created_at=card.created_at,
                note=notes_by_card.get(card.id),
            ),
            topic_name=topic_display_name,
            liked_at=liked_at,
        )
        for liked_at, card, subtopic_title, topic_display_name in rows
    ]


@cards_router.get("/saved", response_model=list[SavedCardOut])
async def get_saved_cards(
    session: SessionDep,
    user_id: UserDep,
    topic_id: UUID | None = Query(default=None, description="Filter to one topic"),
    sort: Literal["recent", "oldest", "topic", "difficulty"] = Query(
        default="recent", description="Sort order"
    ),
) -> list[SavedCardOut]:
    """Every card this user has bookmarked, with enough context to render inline.

    Pure data retrieval — no LLM, no generation, no ranking computation.
    Mirrors `get_liked_cards` exactly, sourcing from `card_bookmark` instead of
    `card_like`. Returns in the requested sort order so the client grid never
    has to re-sort a large collection in JS.
    """

    display_name = func.coalesce(UserTopic.display_name, Topic.canonical_name)

    stmt = (
        select(CardBookmark.created_at, Card, Subtopic.title, display_name)
        .join(Card, Card.id == CardBookmark.card_id)
        .join(Subtopic, Subtopic.id == Card.subtopic_id)
        .join(Topic, Topic.id == Card.topic_id)
        .outerjoin(
            UserTopic,
            (UserTopic.user_id == CardBookmark.user_id)
            & (UserTopic.topic_id == Card.topic_id),
        )
        .where(CardBookmark.user_id == user_id)
    )

    if topic_id is not None:
        stmt = stmt.where(Card.topic_id == topic_id)

    if sort == "recent":
        stmt = stmt.order_by(CardBookmark.created_at.desc())
    elif sort == "oldest":
        stmt = stmt.order_by(CardBookmark.created_at.asc())
    elif sort == "topic":
        stmt = stmt.order_by(display_name.asc(), CardBookmark.created_at.desc())
    elif sort == "difficulty":
        stmt = stmt.order_by(Card.difficulty.asc(), CardBookmark.created_at.desc())

    rows = (await session.execute(stmt)).all()

    if not rows:
        return []

    card_ids = [card.id for _, card, _, _ in rows]
    notes_by_card = await NotesService(session).get_for_cards(user_id, card_ids)

    return [
        SavedCardOut(
            card=CardOut(
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
                visual_id=card.visual_id,
                visual_slots=card.visual_slots,
                created_at=card.created_at,
                note=notes_by_card.get(card.id),
            ),
            topic_name=topic_display_name,
            saved_at=saved_at,
        )
        for saved_at, card, subtopic_title, topic_display_name in rows
    ]
