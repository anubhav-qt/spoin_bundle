"""Upsert/delete/list on `CardNote` -- private, per-user, per-card, never fed to
ranking (see the model's docstring). Kept as its own small service rather than
inlined in the router so `GET /notes` and the feed's bulk lookup share one place
that knows how to join a note back to its card."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.domain.models import Card, CardNote, Subtopic, UserTopic


@dataclass(frozen=True)
class NoteWithCard:
    body: str
    updated_at: datetime
    card: Card
    subtopic_title: str
    topic_name: str


class NotesService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, user_id: UUID, card_id: UUID, body: str) -> CardNote:
        card_exists = await self._session.scalar(select(Card.id).where(Card.id == card_id))
        if card_exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Card not found")

        statement = (
            pg_insert(CardNote)
            .values(user_id=user_id, card_id=card_id, body=body)
            .on_conflict_do_update(
                index_elements=["user_id", "card_id"],
                set_={"body": body},
            )
            .returning(CardNote)
        )
        note = (await self._session.execute(statement)).scalar_one()
        await self._session.flush()
        return note

    async def delete(self, user_id: UUID, card_id: UUID) -> None:
        # Idempotent: deleting a note that never existed (or was already
        # deleted) is not an error -- the client's end state is what it wanted.
        await self._session.execute(
            delete(CardNote).where(CardNote.user_id == user_id, CardNote.card_id == card_id)
        )

    async def get_for_cards(self, user_id: UUID, card_ids: list[UUID]) -> dict[UUID, str]:
        """Bulk lookup for the feed -- keyed by card_id, body only."""

        if not card_ids:
            return {}
        rows = (
            await self._session.execute(
                select(CardNote.card_id, CardNote.body).where(
                    CardNote.user_id == user_id, CardNote.card_id.in_(card_ids)
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    async def list_for_user(self, user_id: UUID) -> list[NoteWithCard]:
        """Every note this user has written, newest edit first, with enough
        card/topic context for the "all my notes" view (task 0004) to render
        without a per-card follow-up request."""

        rows = (
            await self._session.execute(
                select(CardNote, Card, Subtopic.title, UserTopic.display_name)
                .join(Card, Card.id == CardNote.card_id)
                .join(Subtopic, Subtopic.id == Card.subtopic_id)
                .join(
                    UserTopic,
                    (UserTopic.user_id == CardNote.user_id) & (UserTopic.topic_id == Card.topic_id),
                )
                .where(CardNote.user_id == user_id)
                .order_by(CardNote.updated_at.desc())
            )
        ).all()

        return [
            NoteWithCard(
                body=note.body,
                updated_at=note.updated_at,
                card=card,
                subtopic_title=subtopic_title,
                topic_name=topic_display_name,
            )
            for note, card, subtopic_title, topic_display_name in rows
        ]
