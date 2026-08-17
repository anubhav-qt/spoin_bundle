"""Authentication router.

Handles registration, login, guest sessions, Google OAuth, and token refresh.
These endpoints are public (no authentication required) except `/me`, `/claim`,
and (conditionally) `/google` — see `OptionalUserDep` on that one.

**Guests** (ADR-0033): `/auth/guest` mints a real `User` row with no email —
`User.is_guest` (domain/models/topic.py) is derived from that. `/auth/claim`
attaches email/password to that SAME row so a guest's progress carries over
instead of starting a fresh account. `/auth/google` does the equivalent link
when the caller is already signed in as a guest.
"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from spoin.api.deps import OptionalUserDep, SessionDep, SettingsDep, UserDep
from spoin.api.schemas import (
    GoogleAuthIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserOut,
)
from spoin.auth.google import verify_google_id_token
from spoin.auth.passwords import hash_password, verify_password
from spoin.auth.rate_limit import login_rate_limiter, register_rate_limiter
from spoin.auth.tokens import create_token_pair, decode_token
from spoin.domain.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_guest=user.is_guest,
        onboarding_complete=user.onboarding_complete,
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterIn, request: Request, session: SessionDep, settings: SettingsDep
) -> TokenOut:
    register_rate_limiter.check(f"{_client_ip(request)}:{payload.email}")

    exists = await session.scalar(select(User.id).where(User.email == payload.email))
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    await session.commit()

    tokens = create_token_pair(user.id, settings)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
    )


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn, request: Request, session: SessionDep, settings: SettingsDep
) -> TokenOut:
    login_rate_limiter.check(f"{_client_ip(request)}:{payload.email}")

    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None or user.password_hash is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    tokens = create_token_pair(user.id, settings)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
    )


@router.post("/guest", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def guest(session: SessionDep, settings: SettingsDep) -> TokenOut:
    """Create a fresh anonymous user and issue tokens immediately, so a guest's
    swipes, likes, and progress persist against a real `user_id` from their very
    first card — see overview.md, "cards are shared, not personal": progression
    and engagement are keyed off `user_id` everywhere, guest or not."""
    user = User(email=None, display_name="Guest")
    session.add(user)
    await session.commit()

    tokens = create_token_pair(user.id, settings)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
    )


@router.post("/claim", response_model=TokenOut)
async def claim(
    payload: RegisterIn, session: SessionDep, settings: SettingsDep, user_id: UserDep
) -> TokenOut:
    """Attach email/password to the CALLER's own guest account, in place — never
    creates a new row, so `user_id` and everything keyed off it (topics, progress,
    engagement) carries over untouched."""
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.is_guest:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Account is already claimed")

    exists = await session.scalar(select(User.id).where(User.email == payload.email))
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

    user.email = payload.email
    user.display_name = payload.display_name
    user.password_hash = hash_password(payload.password)
    await session.commit()

    tokens = create_token_pair(user.id, settings)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
    )


@router.post("/google", response_model=TokenOut)
async def google_auth(
    payload: GoogleAuthIn,
    session: SessionDep,
    settings: SettingsDep,
    caller_user_id: OptionalUserDep,
) -> TokenOut:
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Google auth not configured")

    try:
        user_info = verify_google_id_token(payload.id_token, settings.google_client_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user = await session.scalar(select(User).where(User.google_id == user_info.google_id))

    if user is None:
        # A signed-in guest linking Google takes priority over matching by
        # email: it is the guest's OWN carried-over identity, not a fresh
        # account, so their existing user_id (and everything keyed off it)
        # survives instead of a duplicate row appearing.
        caller = await session.get(User, caller_user_id) if caller_user_id else None
        if caller is not None and caller.is_guest:
            caller.email = user_info.email
            caller.google_id = user_info.google_id
            caller.display_name = user_info.name
            user = caller
        else:
            user = await session.scalar(select(User).where(User.email == user_info.email))
            if user is not None:
                user.google_id = user_info.google_id
            else:
                user = User(
                    email=user_info.email,
                    display_name=user_info.name,
                    google_id=user_info.google_id,
                )
                session.add(user)

        await session.commit()

    tokens = create_token_pair(user.id, settings)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
    )


@router.post("/refresh", response_model=TokenOut)
async def refresh(payload: RefreshIn, session: SessionDep, settings: SettingsDep) -> TokenOut:
    try:
        decoded = decode_token(payload.refresh_token, settings)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if decoded.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    # We could theoretically just trust the token, but checking if the user still
    # exists is a good sanity check.
    user_id_str = decoded.get("sub")
    if not user_id_str:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    user = await session.scalar(select(User).where(User.id == user_id_str))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")

    tokens = create_token_pair(user.id, settings)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
    )


@router.get("/me", response_model=UserOut)
async def get_me(session: SessionDep, user_id: UserDep) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    return _user_out(user)
