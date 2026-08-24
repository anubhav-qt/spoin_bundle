"""Feed endpoints and liked-card collection.

**No LLM call may appear in this module or anything it reaches.** Hard rule 1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from spoin.api.deps import OptionalUserDep, SessionDep, SettingsDep, UserDep
from spoin.api.schemas import CardOut, FeedOut, LikedCardOut, SavedCardOut
from spoin.domain.enums import SeenState
from spoin.domain.models import (
    Card,
    CardBookmark,
    CardLike,
    Subtopic,
    Topic,
    UserCardState,
    UserTopic,
)
from spoin.feed.service import FeedService
from spoin.notes.service import NotesService

CollectionSort = Literal["recent", "oldest", "topic", "difficulty"]

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
        recycling=page.recycling,
    )


#: The two collection endpoints below differ only in which join table they read
#: from. Everything else — the joins, the four sort orders, the note lookup, the
#: CardOut construction — was duplicated line for line (74% identical by diff,
#: and `get_saved_cards`'s own docstring said "Mirrors get_liked_cards exactly").
#: Two copies of a query is two places to fix the next time the card shape
#: changes, which it has repeatedly (archetype, visual_slots, note).
_CollectionModel = type[CardLike] | type[CardBookmark]


async def _collection(
    session: SessionDep,
    user_id: UUID,
    model: _CollectionModel,
    topic_id: UUID | None,
    sort: CollectionSort,
) -> list[tuple[datetime, Card, str, str, str | None, bool]]:
    """Rows for one card collection: (collected_at, card, subtopic title, topic
    label, note body, seen).

    Pure retrieval — no LLM, no generation, no ranking. Returns in the requested
    sort order so the client never has to re-sort a large collection in JS.

    Notes come from a second query (the same deliberate separation the feed
    endpoint uses — they are private state, never mixed into the card query).
    """

    display_name = func.coalesce(UserTopic.display_name, Topic.canonical_name)

    stmt = (
        select(
            model.created_at,
            Card,
            Subtopic.title,
            display_name,
            UserCardState.state == SeenState.SEEN,
        )
        .join(Card, Card.id == model.card_id)
        .join(Subtopic, Subtopic.id == Card.subtopic_id)
        .join(Topic, Topic.id == Card.topic_id)
        .outerjoin(
            UserTopic,
            (UserTopic.user_id == model.user_id) & (UserTopic.topic_id == Card.topic_id),
        )
        # Left, not inner: a card can be bookmarked/liked without ever having
        # been dwelt on or explicitly marked read, and must still show up here
        # as unseen rather than being dropped from the collection entirely.
        .outerjoin(
            UserCardState,
            (UserCardState.user_id == model.user_id) & (UserCardState.card_id == Card.id),
        )
        .where(model.user_id == user_id)
    )

    if topic_id is not None:
        stmt = stmt.where(Card.topic_id == topic_id)

    if sort == "recent":
        stmt = stmt.order_by(model.created_at.desc())
    elif sort == "oldest":
        stmt = stmt.order_by(model.created_at.asc())
    elif sort == "topic":
        stmt = stmt.order_by(display_name.asc(), model.created_at.desc())
    elif sort == "difficulty":
        stmt = stmt.order_by(Card.difficulty.asc(), model.created_at.desc())

    rows = (await session.execute(stmt)).all()
    if not rows:
        return []

    notes_by_card = await NotesService(session).get_for_cards(
        user_id, [card.id for _, card, _, _, _ in rows]
    )
    return [
        (
            collected_at,
            card,
            subtopic_title,
            topic_display_name,
            notes_by_card.get(card.id),
            bool(seen),
        )
        for collected_at, card, subtopic_title, topic_display_name, seen in rows
    ]


def _card_out(card: Card, subtopic_title: str, note: str | None, seen: bool = False) -> CardOut:
    return CardOut(
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
        note=note,
        seen=seen,
    )


@cards_router.get("/liked", response_model=list[LikedCardOut])
async def get_liked_cards(
    session: SessionDep,
    user_id: UserDep,
    topic_id: UUID | None = Query(default=None, description="Filter to one topic"),
    sort: CollectionSort = Query(default="recent", description="Sort order"),
) -> list[LikedCardOut]:
    """Every card this user has liked, with enough context to render inline."""

    rows = await _collection(session, user_id, CardLike, topic_id, sort)
    return [
        LikedCardOut(
            card=_card_out(card, subtopic_title, note, seen),
            topic_name=topic_display_name,
            liked_at=collected_at,
        )
        for collected_at, card, subtopic_title, topic_display_name, note, seen in rows
    ]


@cards_router.get("/saved", response_model=list[SavedCardOut])
async def get_saved_cards(
    session: SessionDep,
    user_id: UserDep,
    topic_id: UUID | None = Query(default=None, description="Filter to one topic"),
    sort: CollectionSort = Query(default="recent", description="Sort order"),
) -> list[SavedCardOut]:
    """Every card this user has bookmarked. Same shape as `/cards/liked`,
    sourced from `card_bookmark` instead of `card_like`."""

    rows = await _collection(session, user_id, CardBookmark, topic_id, sort)
    return [
        SavedCardOut(
            card=_card_out(card, subtopic_title, note, seen),
            topic_name=topic_display_name,
            saved_at=collected_at,
        )
        for collected_at, card, subtopic_title, topic_display_name, note, seen in rows
    ]


@cards_router.get("/{card_id}", response_model=CardOut)
async def get_card(
    card_id: UUID,
    session: SessionDep,
    user_id: OptionalUserDep,
) -> CardOut:
    """Fetch a single card by its UUID for direct linking and share spaces."""
    row = (
        await session.execute(
            select(Card, Subtopic.title)
            .join(Subtopic, Subtopic.id == Card.subtopic_id)
            .where(Card.id == card_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Card not found")
    card, subtopic_title = row
    note = None
    if user_id is not None:
        notes_by_card = await NotesService(session).get_for_cards(user_id, [card_id])
        note = notes_by_card.get(card_id)
    return _card_out(card, subtopic_title, note)
