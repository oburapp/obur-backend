"""Check-in-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.database import get_session
from app.exceptions import (
    CheckinNotFoundError,
    DuplicateProductRatingError,
    EmptyProductListError,
    FutureVisitDateError,
    NotCheckinOwnerError,
    ProductNotAtVenueError,
    VenueNotFoundError,
)
from app.models.checkin import Checkin
from app.models.user import User
from app.schemas.checkin import (
    CheckinCreateRequest,
    CheckinResponse,
    CheckinUpdateRequest,
)
from app.services import checkin as checkin_service
from app.services.checkin import ProductRating

router = APIRouter(prefix="/checkins", tags=["checkins"])


async def _build_response(session: AsyncSession, checkin: Checkin) -> CheckinResponse:
    products = await checkin_service.get_products_for_checkins(session, [checkin.id])
    return CheckinResponse.from_models(checkin, products.get(checkin.id, []))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_checkin(
    payload: CheckinCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinResponse:
    """Create a check-in: one visit, its optional venue-level ratings,
    and every rated product, in a single transaction.
    """
    try:
        checkin = await checkin_service.create_checkin(
            session,
            user_id=current_user.id,
            venue_id=payload.venue_id,
            products=[
                ProductRating(product_id=p.product_id, rating=p.rating)
                for p in payload.products
            ],
            visited_at=payload.visited_at,
            visited_tz=payload.visited_tz,
            rating_service=payload.rating_service,
            rating_ambiance=payload.rating_ambiance,
            rating_value=payload.rating_value,
            note=payload.note,
            photo_url=payload.photo_url,
            is_public=payload.is_public,
        )
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found"
        ) from e
    except (
        EmptyProductListError,
        DuplicateProductRatingError,
        ProductNotAtVenueError,
        FutureVisitDateError,
    ) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        ) from e

    return await _build_response(session, checkin)


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
            status_code=status.HTTP_404_NOT_FOUND, detail="Checkin not found"
        ) from e

    return await _build_response(session, checkin)


@router.patch("/{checkin_id}")
async def update_checkin(
    checkin_id: UUID,
    payload: CheckinUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinResponse:
    """Update a check-in's editable fields. Owner or admin only. The
    rated products themselves aren't editable through this endpoint.
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
            status_code=status.HTTP_404_NOT_FOUND, detail="Checkin not found"
        ) from e
    except NotCheckinOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except FutureVisitDateError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        ) from e

    return await _build_response(session, checkin)


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
            status_code=status.HTTP_404_NOT_FOUND, detail="Checkin not found"
        ) from e
    except NotCheckinOwnerError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
