"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.auth.tokens import decode_token
from spoin.core.config import Settings, get_settings
from spoin.core.db import get_session
from spoin.core.logging import user_id_var
from spoin.domain.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_bearer = HTTPBearer()
_bearer_optional = HTTPBearer(auto_error=False)


async def _resolve_access_token_user_id(
    session: AsyncSession, settings: Settings, token: str
) -> UUID:
    try:
        payload = decode_token(token, settings)
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token expired") from e
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject") from e

    exists = await session.scalar(select(User.id).where(User.id == user_id))
    if exists is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return exists


async def current_user_id(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> UUID:
    """Resolve the acting user via JWT Bearer token."""
    user_id = await _resolve_access_token_user_id(session, settings, credentials.credentials)
    # Every log line emitted for the rest of this request carries the acting
    # user (see core/logging.py's ContextFilter). A UUID, never an email —
    # enough to correlate a report with its request, not a PII leak into logs.
    user_id_var.set(str(user_id))
    return user_id


async def current_user_id_optional(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_optional)],
) -> UUID | None:
    """Same as `current_user_id`, but None (never a 401) when no/invalid token is
    presented. Only for endpoints that are valid both signed-out and signed-in —
    e.g. `/auth/google`, which needs to know whether the caller is a signed-in
    guest claiming their account vs. a fresh sign-in."""
    if credentials is None:
        return None
    try:
        return await _resolve_access_token_user_id(session, settings, credentials.credentials)
    except HTTPException:
        return None


UserDep = Annotated[UUID, Depends(current_user_id)]
OptionalUserDep = Annotated[UUID | None, Depends(current_user_id_optional)]
