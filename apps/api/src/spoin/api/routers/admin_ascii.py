"""Operator review of a topic's ASCII scenes (ADR-0104).

Mounted only when `env != "production"`, the same placeholder gate as
`/admin/repairs` and `/dev/*` -- there is no admin role yet (task 0035), and
these endpoints edit live card content.

Keyed by topic SLUG rather than id because the page is reached by typing a URL
(`/admin/rust/ascii-art`), and an operator knows the slug.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import (
    AsciiSceneActionOut,
    AsciiSceneKeepIn,
    AsciiSceneOut,
    AsciiSceneRejectIn,
)
from spoin.moderation.ascii_review import AsciiReviewService

router = APIRouter(prefix="/admin/ascii", tags=["admin"])


@router.get("/{topic_slug}", response_model=list[AsciiSceneOut])
async def list_scenes(
    topic_slug: str, session: SessionDep, user_id: UserDep
) -> list[AsciiSceneOut]:
    scenes = await AsciiReviewService(session).list_scenes(topic_slug)
    return [AsciiSceneOut.model_validate(scene) for scene in scenes]


@router.post("/scene/{card_id}/keep", response_model=AsciiSceneActionOut)
async def keep_scene(
    card_id: UUID, payload: AsciiSceneKeepIn, session: SessionDep, user_id: UserDep
) -> AsciiSceneActionOut:
    """Accept the scene as it stands, writing the operator's edit to the card."""

    result = await AsciiReviewService(session).keep(card_id, payload.art, payload.alt)
    return AsciiSceneActionOut.model_validate(result)


@router.post("/scene/{card_id}/reject", response_model=AsciiSceneActionOut)
async def reject_scene(
    card_id: UUID, payload: AsciiSceneRejectIn, session: SessionDep, user_id: UserDep
) -> AsciiSceneActionOut:
    """File an `art` report so the card lands in `/admin/repairs` (ADR-0076)."""

    result = await AsciiReviewService(session).send_to_repairs(card_id, user_id, payload.note)
    return AsciiSceneActionOut.model_validate(result)
