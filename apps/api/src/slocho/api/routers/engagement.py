"""Engagement ingest."""

from __future__ import annotations

from fastapi import APIRouter, status

from slocho.api.deps import SessionDep, SettingsDep, UserDep
from slocho.api.schemas import EngagementAck, EngagementBatchIn
from slocho.engagement.service import EngagementService, IncomingEvent

router = APIRouter(prefix="/engagement", tags=["engagement"])


@router.post("/events", response_model=EngagementAck, status_code=status.HTTP_202_ACCEPTED)
async def ingest_events(
    payload: EngagementBatchIn,
    session: SessionDep,
    settings: SettingsDep,
    user_id: UserDep,
) -> EngagementAck:
    """Accept a buffered batch from the client.

    202, not 201: engagement is eventually consistent by design, and the client
    must not read back its own writes for anything that matters.

    Still to add before this faces real traffic: a per-user rate limit. A buggy
    client loop is indistinguishable from an attack (ADR-0011).
    """

    service = EngagementService(session, settings)
    result = await service.ingest(
        user_id,
        [
            IncomingEvent(
                id=event.id,
                card_id=event.card_id,
                kind=event.kind,
                dwell_ms=event.dwell_ms,
                client_occurred_at=event.client_occurred_at,
                session_id=event.session_id,
            )
            for event in payload.events
        ],
    )
    await session.commit()

    return EngagementAck(
        accepted=result.accepted,
        duplicates=result.duplicates,
        rejected=result.rejected,
    )
