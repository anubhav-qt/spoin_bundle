"""AskAI: `POST /cards/{card_id}/ask` -> Server-Sent Events (ADR-0077).

The first streaming endpoint in the codebase. Validation that needs an HTTP
status (unknown card, empty question) happens before the stream opens; anything
after is an SSE `error` / `off_topic` / `limit` event, never a status code.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from spoin.api.deps import SessionDep, UserDep
from spoin.ask.service import AskService, normalize_question, question_count_today
from spoin.core.config import get_settings
from spoin.domain.enums import CardStatus
from spoin.domain.models import Card
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator

router = APIRouter(prefix="/cards", tags=["ask"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AskQuotaOut(BaseModel):
    spent: int
    limit: int


@router.get("/ask/quota", response_model=AskQuotaOut, tags=["ask"])
async def ask_quota(session: SessionDep, user_id: UserDep) -> AskQuotaOut:
    return AskQuotaOut(
        spent=await question_count_today(session, user_id),
        limit=get_settings().ask_ai_daily_limit,
    )


@router.post("/{card_id}/ask")
async def ask_card(
    card_id: UUID, payload: AskIn, session: SessionDep, user_id: UserDep
) -> StreamingResponse:
    if not normalize_question(payload.question):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Empty question")
    card = await session.scalar(
        select(Card.id).where(Card.id == card_id, Card.status == CardStatus.ACTIVE)
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such card")

    service = AskService(
        session, get_settings(), get_content_generator(), get_embedder()
    )

    async def _sse() -> AsyncIterator[bytes]:
        async for event, data in service.answer(user_id, card_id, payload.question):
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
