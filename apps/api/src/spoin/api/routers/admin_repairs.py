"""Operator triage for reported cards (ADR-0076).

Mounted only when `env != "production"` (see `api/main.py`), same placeholder
gate as `/dev/*` -- there is no admin role yet (task 0035). The destructive
actions here (retire a card, spend LLM calls) are why that task matters.

The card is rendered to a PNG **by the admin page**, client-side, with the same
`html-to-image` call the share button uses, and uploaded here. The worker never
renders.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, UploadFile

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import RepairEnqueuedOut, RepairQueueItemOut
from spoin.moderation.service import ModerationService
from spoin.profile.images import read_validated_image

router = APIRouter(prefix="/admin/repairs", tags=["admin"])


@router.get("", response_model=list[RepairQueueItemOut])
async def list_repair_queue(session: SessionDep, user_id: UserDep) -> list[RepairQueueItemOut]:
    return await ModerationService(session).list_queue()


@router.post("/{card_id}/delete", response_model=RepairEnqueuedOut)
async def delete_card(card_id: UUID, session: SessionDep, user_id: UserDep) -> RepairEnqueuedOut:
    return await ModerationService(session).delete_card(card_id)


@router.post("/{card_id}/dismiss", response_model=RepairEnqueuedOut)
async def dismiss_repair(card_id: UUID, session: SessionDep, user_id: UserDep) -> RepairEnqueuedOut:
    """Clear a resolved (done/failed) repair's before/after entry from the queue."""
    return await ModerationService(session).dismiss(card_id)


@router.post("/{card_id}/fix", response_model=RepairEnqueuedOut)
async def enqueue_fix(
    card_id: UUID,
    session: SessionDep,
    user_id: UserDep,
    file: UploadFile,
    guidance: Annotated[str | None, Form(max_length=4000)] = None,
) -> RepairEnqueuedOut:
    """Structure-only repair informed by the rendered card image. `guidance` is
    optional -- with it, the repair may also change prose (ADR-0076); without
    it, the model is told to keep the words and fix only the structure."""

    image = await read_validated_image(file)
    clean = (guidance or "").strip() or None
    return await ModerationService(session).enqueue_fix(card_id, image=image.data, guidance=clean)


@router.post("/{card_id}/remake", response_model=RepairEnqueuedOut)
async def enqueue_remake(
    card_id: UUID,
    session: SessionDep,
    user_id: UserDep,
    instructions: Annotated[str, Form(min_length=1, max_length=4000)],
    file: UploadFile | None = None,
) -> RepairEnqueuedOut:
    """Regenerate the card from scratch to `instructions` (required), through
    the normal quality gate. The image is optional here -- a remake is not
    working from the old visual."""

    image = (await read_validated_image(file)).data if file is not None else None
    return await ModerationService(session).enqueue_remake(
        card_id, instructions=instructions.strip(), image=image
    )
