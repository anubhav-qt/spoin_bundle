from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import (
    DailyGoalOut,
    ProfileExportOut,
    ProfileStatsOut,
    UserOut,
    UserProfileUpdateIn,
)
from spoin.domain.models import User
from spoin.profile.images import read_validated_image
from spoin.profile.service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/me", response_model=UserOut)
async def get_profile(user_id: UserDep, session: SessionDep) -> User:
    """Returns the authenticated user's profile information."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/me", response_model=UserOut)
async def update_profile(
    updates: UserProfileUpdateIn, user_id: UserDep, session: SessionDep
) -> User:
    """Updates the user's profile."""
    service = ProfileService(session)
    return await service.update_profile(user_id, updates)


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(file: UploadFile, user_id: UserDep, session: SessionDep) -> User:
    """Uploads and saves a custom avatar image.

    Validation is by magic bytes and a streaming byte cap — see
    profile/images.py for why the request's own `content_type` is not trusted
    and why the size check cannot happen after the body is already buffered.
    """
    image = await read_validated_image(file)
    service = ProfileService(session)
    return await service.update_avatar_image(user_id, image)


@router.delete("/me/avatar", response_model=UserOut)
async def delete_avatar(user_id: UserDep, session: SessionDep) -> User:
    """Removes the user's custom avatar."""
    service = ProfileService(session)
    return await service.delete_avatar_image(user_id)


@router.get("/me/avatar/image")
async def get_avatar_image(user_id: UserDep, session: SessionDep) -> Response:
    """The raw avatar bytes, served as whatever they actually are.

    This used to answer `image/jpeg` unconditionally with a comment admitting
    it was "very crude guessing"; the type is sniffed at upload time now and
    stored alongside the blob.
    """
    try:
        data, media_type = await ProfileService(session).load_avatar_image(user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="No avatar image found") from None
    return Response(content=data, media_type=media_type)


@router.get("/me/export", response_model=ProfileExportOut)
async def export_profile_data(
    user_id: UserDep,
    session: SessionDep,
) -> ProfileExportOut:
    """The user's own data as JSON (Settings -> Data & Privacy).

    A plain serving-layer read: their topics, notes, likes, bookmarks and daily
    activity. No generation, no LLM. The client saves the response as a file --
    doing the download client-side keeps this a normal JSON endpoint that is
    also usable from a script or the API docs, rather than one that only makes
    sense when a browser is driving it.
    """
    service = ProfileService(session)
    return await service.export_data(user_id)


@router.get("/me/stats", response_model=ProfileStatsOut)
async def get_profile_stats(
    year: int, month: int, user_id: UserDep, session: SessionDep
) -> ProfileStatsOut:
    """Returns the user's aggregated statistics, streaks, and heatmap."""
    service = ProfileService(session)
    return await service.get_profile_stats(user_id, year, month)


@router.get("/me/today", response_model=DailyGoalOut)
async def get_today_progress(
    user_id: UserDep, session: SessionDep, tz_offset_minutes: int = 0
) -> DailyGoalOut:
    """Cards read today (the caller's local day, ADR-0060) against
    `daily_card_goal` -- the right rail's daily-goal ring."""
    service = ProfileService(session)
    return await service.get_today_progress(user_id, tz_offset_minutes)
