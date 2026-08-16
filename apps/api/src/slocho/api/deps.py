"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slocho.core.config import Settings, get_settings
from slocho.core.db import get_session
from slocho.domain.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def current_user_id(
    session: SessionDep,
    x_user_id: Annotated[UUID | None, Header(alias="X-User-Id")] = None,
) -> UUID:
    """Resolve the acting user.

    **Placeholder auth.** A header is not authentication and this must be replaced
    before anything is exposed publicly. It is a header rather than a hardcoded id
    so that every downstream signature already takes a `user_id` — swapping in real
    token verification then changes this function and nothing else.
    """

    if x_user_id is None:
        # Single-user convenience for local development and the seeded demo.
        user_id = await session.scalar(select(User.id).order_by(User.created_at).limit(1))
        if user_id is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="No users exist. Run the seed job first.",
            )
        return user_id

    exists = await session.scalar(select(User.id).where(User.id == x_user_id))
    if exists is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return exists


UserDep = Annotated[UUID, Depends(current_user_id)]
