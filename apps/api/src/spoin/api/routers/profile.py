from datetime import datetime, UTC
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File

from spoin.api.deps import UserDep, SessionDep
from spoin.api.schemas import ProfileStatsOut, UserOut, UserProfileUpdateIn
from spoin.domain.models import User
from spoin.profile.service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])

@router.get("/me", response_model=UserOut)
async def get_profile(user_id: UserDep, session: SessionDep) -> User:
    """Returns the authenticated user's profile information."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Ensure has_avatar_image is dynamically calculated
    user.has_avatar_image = user.avatar_image is not None
    return user

@router.patch("/me", response_model=UserOut)
async def update_profile(
    updates: UserProfileUpdateIn,
    user_id: UserDep,
    session: SessionDep
) -> User:
    """Updates the user's profile."""
    service = ProfileService(session)
    updated_user = await service.update_profile(user_id, updates)
    updated_user.has_avatar_image = updated_user.avatar_image is not None
    return updated_user

@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile,
    user_id: UserDep,
    session: SessionDep
) -> User:
    """Uploads and saves a custom avatar image."""
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image format. Only JPEG, PNG, and WebP are supported.",
        )
    
    # We could restrict size but FastAPI limits uploads anyway or we can check file size.
    image_bytes = await file.read()
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image is too large. Maximum size is 5MB.",
        )
        
    service = ProfileService(session)
    updated_user = await service.update_avatar_image(user_id, image_bytes)
    updated_user.has_avatar_image = True
    return updated_user

@router.delete("/me/avatar", response_model=UserOut)
async def delete_avatar(
    user_id: UserDep,
    session: SessionDep
) -> User:
    """Removes the user's custom avatar."""
    service = ProfileService(session)
    updated_user = await service.delete_avatar_image(user_id)
    updated_user.has_avatar_image = False
    return updated_user

@router.get("/me/avatar/image")
async def get_avatar_image(
    user_id: UserDep,
    session: SessionDep
):
    """Returns the raw avatar image bytes for display."""
    from fastapi.responses import Response
    user = await session.get(User, user_id)
    if not user or not user.avatar_image:
        raise HTTPException(status_code=404, detail="No avatar image found")
    
    # Very crude guessing of mime type, in production we'd save mime type or infer it from magic bytes
    return Response(content=user.avatar_image, media_type="image/jpeg")

@router.get("/me/stats", response_model=ProfileStatsOut)
async def get_profile_stats(
    year: int,
    month: int,
    user_id: UserDep,
    session: SessionDep
) -> ProfileStatsOut:
    """Returns the user's aggregated statistics, streaks, and heatmap."""
    service = ProfileService(session)
    return await service.get_profile_stats(user_id, year, month)
