"""CardNote upsert/delete/list -- see docs/tasks/0004-notes-in-one-place.md."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.domain.models import CardNote
from spoin.notes.service import NotesService

pytestmark = pytest.mark.asyncio


async def test_upsert_creates_then_updates_in_place(
    session: AsyncSession, corpus: dict[str, Any]
) -> None:
    """A user should be able to edit a note they already wrote, not append."""

    service = NotesService(session)
    user, card = corpus["user"], corpus["cards"][0]

    await service.upsert(user.id, card.id, "first draft")
    note = await service.upsert(user.id, card.id, "revised")

    assert note.body == "revised"
    total = await session.scalar(select(func.count()).select_from(CardNote))
    assert total == 1


async def test_upsert_unknown_card_is_404(session: AsyncSession, corpus: dict[str, Any]) -> None:
    service = NotesService(session)
    user = corpus["user"]

    with pytest.raises(HTTPException) as exc_info:
        await service.upsert(user.id, uuid4(), "orphaned")

    assert exc_info.value.status_code == 404


async def test_delete_removes_the_row(session: AsyncSession, corpus: dict[str, Any]) -> None:
    service = NotesService(session)
    user, card = corpus["user"], corpus["cards"][0]

    await service.upsert(user.id, card.id, "temporary")
    await service.delete(user.id, card.id)

    total = await session.scalar(select(func.count()).select_from(CardNote))
    assert total == 0


async def test_delete_is_idempotent(session: AsyncSession, corpus: dict[str, Any]) -> None:
    """Deleting a note that never existed is not an error -- the caller's
    desired end state (no note) already holds."""

    service = NotesService(session)
    user, card = corpus["user"], corpus["cards"][0]

    await service.delete(user.id, card.id)  # should not raise


async def test_notes_are_private_per_user(session: AsyncSession, corpus: dict[str, Any]) -> None:
    from spoin.domain.models import User

    service = NotesService(session)
    card = corpus["cards"][0]
    other = User(email=f"{uuid4()}@test.local", display_name="Other")
    session.add(other)
    await session.flush()

    await service.upsert(corpus["user"].id, card.id, "mine")

    notes_for_other = await service.get_for_cards(other.id, [card.id])
    assert notes_for_other == {}

    notes_for_owner = await service.get_for_cards(corpus["user"].id, [card.id])
    assert notes_for_owner == {card.id: "mine"}


async def test_list_for_user_orders_newest_edit_first(
    session: AsyncSession, corpus: dict[str, Any]
) -> None:
    service = NotesService(session)
    user = corpus["user"]
    first_card, second_card = corpus["cards"][0], corpus["cards"][1]

    await service.upsert(user.id, first_card.id, "written first")
    await service.upsert(user.id, second_card.id, "written second")
    # Editing the first note again should bump it back to the front.
    await service.upsert(user.id, first_card.id, "written first, edited last")

    rows = await service.list_for_user(user.id)

    assert [row.card.id for row in rows] == [first_card.id, second_card.id]
    assert rows[0].body == "written first, edited last"
    assert rows[0].topic_name == "Testing"


async def test_list_for_user_excludes_other_users_notes(
    session: AsyncSession, corpus: dict[str, Any]
) -> None:
    from spoin.domain.models import User

    service = NotesService(session)
    card = corpus["cards"][0]
    other = User(email=f"{uuid4()}@test.local", display_name="Other")
    session.add(other)
    await session.flush()

    await service.upsert(corpus["user"].id, card.id, "mine")

    assert await service.list_for_user(other.id) == []
