"""Check-in-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.database import get_session
from app.exceptions import (
    BookmarkNotFoundError,
    CheckinNotFoundError,
    FutureVisitDateError,
    LikeNotFoundError,
    NotCheckinOwnerError,
    VenueNotFoundError,
)
from app.models.user import User
from app.schemas.checkin import (
    CheckinCreateRequest,
    CheckinResponse,
    CheckinUpdateRequest,
)
from app.services import bookmark as bookmark_service
from app.services import checkin as checkin_service
from app.services import like as like_service

_CHECKIN_NOT_FOUND_DETAIL = "Checkin not found"

router = APIRouter(prefix="/checkins", tags=["checkins"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_checkin(
    payload: CheckinCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinResponse:
    """Create a check-in: one visit and its venue-level ratings."""
    try:
        checkin = await checkin_service.create_checkin(
            session,
            user_id=current_user.id,
            venue_id=payload.venue_id,
            visited_at=payload.visited_at,
            visited_tz=payload.visited_tz,
            rating_taste=payload.rating_taste,
            rating_service=payload.rating_service,
            rating_ambiance=payload.rating_ambiance,
            rating_value=payload.rating_value,
            note=payload.note,
            photo_url=payload.photo_url,
            visibility=payload.visibility,
        )
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found"
        ) from e
    except FutureVisitDateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        ) from e

    return CheckinResponse.model_validate(checkin)


@router.get("/{checkin_id}")
async def get_checkin(
    checkin_id: UUID,
    viewer: User | None = Depends(get_optional_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinResponse:
    """Return a single check-in. A private check-in is only visible to
    its owner or an admin — anyone else gets 404, the same as if it
    didn't exist.
    """
    try:
        checkin = await checkin_service.get_checkin(session, checkin_id, viewer=viewer)
    except CheckinNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHECKIN_NOT_FOUND_DETAIL
        ) from e

    return CheckinResponse.model_validate(checkin)


@router.patch("/{checkin_id}")
async def update_checkin(
    checkin_id: UUID,
    payload: CheckinUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinResponse:
    """Update a check-in's editable fields. Owner or admin only. The
    see ADR-0011 in obur-docs for what stays editable.
    """
    try:
        checkin = await checkin_service.update_checkin(
            session,
            checkin_id,
            current_user=current_user,
            updates=payload.model_dump(exclude_unset=True),
        )
    except CheckinNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHECKIN_NOT_FOUND_DETAIL
        ) from e
    except NotCheckinOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except FutureVisitDateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        ) from e

    return CheckinResponse.model_validate(checkin)


@router.delete("/{checkin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checkin(
    checkin_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft-delete a check-in. Owner or admin only, and always soft —
    see app.api.v1.admin for permanent deletion.
    """
    try:
        await checkin_service.soft_delete_checkin(
            session, checkin_id, current_user=current_user
        )
    except CheckinNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHECKIN_NOT_FOUND_DETAIL
        ) from e
    except NotCheckinOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e


@router.post("/{checkin_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def like_checkin(
    checkin_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Like a check-in. Idempotent. Liking a check-in you can't see
    isn't possible — same visibility rules as `get_checkin`.
    """
    try:
        await like_service.like_checkin(session, checkin_id, current_user=current_user)
    except CheckinNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHECKIN_NOT_FOUND_DETAIL
        ) from e


@router.delete("/{checkin_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_checkin(
    checkin_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Un-like a check-in."""
    try:
        await like_service.unlike_checkin(
            session, checkin_id, current_user=current_user
        )
    except LikeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Checkin not liked"
        ) from e


@router.post("/{checkin_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def bookmark_checkin(
    checkin_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Bookmark a check-in. Idempotent, private — never a social signal."""
    try:
        await bookmark_service.bookmark_checkin(
            session, checkin_id, current_user=current_user
        )
    except CheckinNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_CHECKIN_NOT_FOUND_DETAIL
        ) from e


@router.delete("/{checkin_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def unbookmark_checkin(
    checkin_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove a check-in bookmark."""
    try:
        await bookmark_service.unbookmark_checkin(
            session, checkin_id, current_user=current_user
        )
    except BookmarkNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Checkin not bookmarked"
        ) from e
