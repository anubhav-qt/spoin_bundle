"""Private note-taking on a card. Upsert semantics -- see `NotesService`."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import CardOut, NoteIn, NoteOut, NoteWithCardOut
from spoin.notes.service import NotesService

router = APIRouter(tags=["notes"])


@router.put("/cards/{card_id}/note", response_model=NoteOut)
async def save_note(
    card_id: UUID, payload: NoteIn, session: SessionDep, user_id: UserDep
) -> NoteOut:
    service = NotesService(session)
    note = await service.upsert(user_id, card_id, payload.body)
    await session.commit()
    return NoteOut(card_id=note.card_id, body=note.body, updated_at=note.updated_at)


@router.delete("/cards/{card_id}/note", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(card_id: UUID, session: SessionDep, user_id: UserDep) -> Response:
    service = NotesService(session)
    await service.delete(user_id, card_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notes", response_model=list[NoteWithCardOut])
async def list_notes(session: SessionDep, user_id: UserDep) -> list[NoteWithCardOut]:
    service = NotesService(session)
    rows = await service.list_for_user(user_id)
    return [
        NoteWithCardOut(
            note=NoteOut(card_id=row.card.id, body=row.body, updated_at=row.updated_at),
            card=CardOut(
                id=row.card.id,
                topic_id=row.card.topic_id,
                subtopic_id=row.card.subtopic_id,
                subtopic_title=row.subtopic_title,
                difficulty=row.card.difficulty,
                title=row.card.title,
                summary=row.card.summary,
                body=row.card.body,
                archetype=row.card.archetype,
                is_hero=row.card.is_hero,
                visual_id=row.card.visual_id,
                visual_kind=row.card.visual_kind,
                visual_slots=row.card.visual_slots,
                created_at=row.card.created_at,
                note=row.body,
                seen=row.seen,
            ),
            topic_name=row.topic_name,
        )
        for row in rows
    ]
