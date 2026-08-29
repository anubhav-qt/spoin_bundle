from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from fastapi.responses import Response

from spoin.api.deps import SessionDep, UserDep
from spoin.api.schemas import (
    DailyGoalOut,
    ImportedFontOut,
    PreferencesOut,
    PreferencesUpdateIn,
    ProfileExportOut,
    ProfileStatsOut,
    UserOut,
    UserProfileUpdateIn,
)
from spoin.domain.models import User
from spoin.profile.fonts import read_validated_font
from spoin.profile.images import read_validated_image
from spoin.profile.preferences import PreferencesService
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


@router.get("/me/preferences", response_model=PreferencesOut)
async def get_preferences(user_id: UserDep, session: SessionDep) -> PreferencesOut:
    """Palette, saved themes, font, and imported-font metadata (ADR-0070).

    Also embedded on `/auth/me` for the pre-paint reconcile; this standalone
    read exists for the mobile client and for a manual refetch.
    """
    return await PreferencesService(session).get(user_id)


@router.put("/me/preferences", response_model=PreferencesOut)
async def put_preferences(
    body: PreferencesUpdateIn, user_id: UserDep, session: SessionDep
) -> PreferencesOut:
    """Whole-object replace of palette + saved themes + font. A `custom:<id>`
    palette must be present in `custom_palettes`, and an `import:<id>` font must
    be one the caller owns — both checked server-side (422 otherwise)."""
    return await PreferencesService(session).update(user_id, body)


@router.get("/me/fonts", response_model=list[ImportedFontOut])
async def list_fonts(user_id: UserDep, session: SessionDep) -> list[ImportedFontOut]:
    """Metadata for this user's imported fonts — no bytes."""
    return await PreferencesService(session).list_fonts(user_id)


@router.post("/me/fonts", response_model=ImportedFontOut, status_code=status.HTTP_201_CREATED)
async def upload_font(
    user_id: UserDep,
    session: SessionDep,
    file: UploadFile,
    name: Annotated[str, Form(min_length=1, max_length=80)],
) -> ImportedFontOut:
    """Import a font file. Format is sniffed from magic bytes (never the
    multipart part's declared type), size is capped at 2MB and the body is
    abandoned at the limit — see `profile/fonts.py`, same shape as avatars."""
    validated = await read_validated_font(file)
    return await PreferencesService(session).add_font(user_id, name.strip(), validated)


@router.get("/me/fonts/{font_id}")
async def get_font(font_id: UUID, user_id: UserDep, session: SessionDep) -> Response:
    """The raw font bytes for a client `@font-face` `src`. Scoped to the caller
    in the query — a stranger's id 404s, no distinction leaked. Immutable by id,
    so it caches hard."""
    try:
        data, media_type = await PreferencesService(session).load_font_bytes(user_id, font_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Font not found") from None
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.delete("/me/fonts/{font_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_font(font_id: UUID, user_id: UserDep, session: SessionDep) -> None:
    """Remove an imported font. If it was the active font, the server resets the
    choice to the default in the same transaction."""
    try:
        await PreferencesService(session).delete_font(user_id, font_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Font not found") from None


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
    """Cards read today (the caller's local day, ADR-0062) against
    `daily_card_goal` -- the right rail's daily-goal ring."""
    service = ProfileService(session)
    return await service.get_today_progress(user_id, tz_offset_minutes)
