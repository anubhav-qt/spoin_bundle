"""AskAI: a topic-scoped, persistent conversation (ADR-0077, revised).

`POST /topics/{topic_id}/ask` is the first streaming endpoint in the codebase.
Validation that needs an HTTP status (unknown topic, empty question) happens
before the stream opens; everything after is an SSE `error` / `off_topic` /
`limit` event, never a status code.
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
from spoin.api.schemas import AskConversationOut
from spoin.ask.service import AskService
from spoin.core.config import get_settings
from spoin.domain.models import Topic
from spoin.embeddings import get_embedder
from spoin.generation import get_content_generator

router = APIRouter(prefix="/topics", tags=["ask"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    #: The card the reader is currently on -- a context hint, not the scope.
    card_id: UUID | None = None


def _service(session: SessionDep) -> AskService:
    return AskService(session, get_settings(), get_content_generator(), get_embedder())


@router.get("/{topic_id}/ask", response_model=AskConversationOut)
async def get_conversation(
    topic_id: UUID, session: SessionDep, user_id: UserDep
) -> AskConversationOut:
    return await _service(session).get_conversation(user_id, topic_id)


@router.post("/{topic_id}/ask/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_conversation(topic_id: UUID, session: SessionDep, user_id: UserDep) -> None:
    await _service(session).reset(user_id, topic_id)


@router.post("/{topic_id}/ask")
async def ask(
    topic_id: UUID, payload: AskIn, session: SessionDep, user_id: UserDep
) -> StreamingResponse:
    if not payload.question.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Empty question")
    if await session.scalar(select(Topic.id).where(Topic.id == topic_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such topic")

    service = _service(session)

    async def _sse() -> AsyncIterator[bytes]:
        async for event, data in service.answer(
            user_id, topic_id, payload.question, payload.card_id
        ):
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
