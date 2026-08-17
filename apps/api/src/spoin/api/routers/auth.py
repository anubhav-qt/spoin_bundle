"""Authentication router.

Handles registration, login, Google OAuth, and token refresh.
These endpoints are public (no authentication required) except for `/me`.
"""

from __future__ import annotations

import jwt
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from spoin.api.deps import SessionDep, SettingsDep, UserDep
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
from spoin.auth.tokens import create_token_pair, decode_token
from spoin.domain.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, session: SessionDep, settings: SettingsDep) -> TokenOut:
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
async def login(payload: LoginIn, session: SessionDep, settings: SettingsDep) -> TokenOut:
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


@router.post("/google", response_model=TokenOut)
async def google_auth(
    payload: GoogleAuthIn, session: SessionDep, settings: SettingsDep
) -> TokenOut:
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Google auth not configured")

    try:
        user_info = verify_google_id_token(payload.id_token, settings.google_client_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user = await session.scalar(select(User).where(User.google_id == user_info.google_id))
    
    if user is None:
        # Fallback to check if a user with this email exists but without google_id
        user = await session.scalar(select(User).where(User.email == user_info.email))
        if user is not None:
            # Link google account to existing email account
            user.google_id = user_info.google_id
        else:
            # Create a new user
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
        
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
    )
