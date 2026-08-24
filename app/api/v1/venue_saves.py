"""Venue-save-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.database import get_session
from app.models.user import User
from app.schemas.venue_save import (
    VenueSaveCreateRequest,
    VenueSaveResponse,
    VenueSaveUpdateRequest,
)
from app.services import venue_save as venue_save_service

router = APIRouter(prefix="/venue-saves", tags=["venue-saves"])

_VENUE_SAVE_NOT_FOUND_DETAIL = "Venue save not found"


@router.post("", status_code=status.HTTP_201_CREATED)
async def save_venue(
    payload: VenueSaveCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VenueSaveResponse:
    """Save a venue as visited/wishlist/favorite. Idempotent for the
    same (venue, type) pair.
    """
    save = await venue_save_service.save_venue(
        session,
        user_id=current_user.id,
        venue_id=payload.venue_id,
        type=payload.type,
        visibility=payload.visibility,
    )
    return VenueSaveResponse.model_validate(save)


@router.get("/{venue_save_id}")
async def get_venue_save(
    venue_save_id: UUID,
    viewer: User | None = Depends(get_optional_current_user),
    session: AsyncSession = Depends(get_session),
) -> VenueSaveResponse:
    """Return a single venue save. A private one is only visible to its
    owner or an admin — anyone else gets 404, the same as if it didn't
    exist.
    """
    save = await venue_save_service.get_venue_save(
        session, venue_save_id, viewer=viewer
    )
    return VenueSaveResponse.model_validate(save)


@router.patch("/{venue_save_id}")
async def update_venue_save(
    venue_save_id: UUID,
    payload: VenueSaveUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VenueSaveResponse:
    """Update a venue save's visibility. Owner or admin only."""
    save = await venue_save_service.update_venue_save(
        session,
        venue_save_id,
        current_user=current_user,
        updates=payload.model_dump(exclude_unset=True),
    )
    return VenueSaveResponse.model_validate(save)


@router.delete("/{venue_save_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_venue_save(
    venue_save_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently delete a venue save. Owner or admin only."""
    await venue_save_service.delete_venue_save(
        session, venue_save_id, current_user=current_user
    )
