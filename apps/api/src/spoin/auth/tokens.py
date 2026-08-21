"""JWT token creation and verification.

Access tokens (short-lived) carry the user identity for API calls.
Refresh tokens (long-lived) are exchanged for new access/refresh pairs
without re-entering credentials.

Both use HS256 with the same secret — acceptable for a single-service
deployment. If the API is ever split into multiple services that need to
independently verify tokens, switch to RS256 (asymmetric) so only the
auth service holds the private key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID

import jwt

from spoin.core.config import Settings


class TokenPair(NamedTuple):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def create_access_token(user_id: UUID, settings: Settings) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": expires,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: UUID, settings: Settings) -> str:
    expires = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": expires,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode and verify a JWT. Raises ``jwt.PyJWTError`` on any failure."""
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    return payload


def create_token_pair(user_id: UUID, settings: Settings) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id, settings),
        refresh_token=create_refresh_token(user_id, settings),
    )
