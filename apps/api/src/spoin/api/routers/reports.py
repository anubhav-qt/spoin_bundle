"""Report a card as structurally broken (ADR-0076).

Parse, delegate, serialize -- all logic is in `spoin.moderation.service`. A
report is a DB write, never an LLM call, so this stays out of the feed read path
only by convention, not necessity.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import CardReportIn
from spoin.moderation.service import ModerationService

router = APIRouter(prefix="/cards", tags=["reports"])


@router.post("/{card_id}/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_card(
    card_id: UUID, payload: CardReportIn, session: SessionDep, user_id: UserDep
) -> None:
    """Flag a live card. Idempotent per user+card (a repeat updates the row).
    Guests may report -- it costs nothing and needs no durable account."""

    await ModerationService(session).report_card(user_id, card_id, payload.reason, payload.note)
