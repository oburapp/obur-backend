"""Venue-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.exceptions import (
    DuplicateVenueNearbyError,
    VenueCategoryNotFoundError,
    VenueNotFoundError,
)
from app.models.user import User
from app.schemas.venue import NearbyVenueResponse, VenueCreateRequest, VenueResponse
from app.services import venue as venue_service

router = APIRouter(prefix="/venues", tags=["venues"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_venue(
    payload: VenueCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> VenueResponse:
    """Create a venue. Rejects likely duplicates within 50m unless
    `confirm_duplicate` is set on the payload.
    """
    try:
        venue = await venue_service.create_venue(
            session,
            name=payload.name,
            lat=payload.lat,
            lng=payload.lng,
            category_id=payload.category_id,
            added_by=current_user.id,
            address_note=payload.address_note,
            google_places_id=payload.google_places_id,
            city=payload.city,
            country_code=payload.country_code,
            timezone=payload.timezone,
            confirm_duplicate=payload.confirm_duplicate,
        )
    except VenueCategoryNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        ) from e
    except DuplicateVenueNearbyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=NearbyVenueResponse(nearby_venue_id=e.nearby_venue_id).model_dump(
                mode="json"
            ),
        ) from e

    return VenueResponse.model_validate(venue)


@router.get("")
async def list_venues(
    q: str | None = Query(default=None, description="Turkish full-text search query"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[VenueResponse]:
    """List venues, or full-text search by name when `q` is given."""
    if q is not None:
        venues = await venue_service.search_venues(
            session, q, limit=limit, offset=offset
        )
    else:
        venues = await venue_service.list_venues(session, limit=limit, offset=offset)

    return [VenueResponse.model_validate(venue) for venue in venues]


@router.get("/{venue_id}")
async def get_venue(
    venue_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> VenueResponse:
    """Return a single venue by id."""
    try:
        venue = await venue_service.get_venue(session, venue_id)
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found"
        ) from e

    return VenueResponse.model_validate(venue)
