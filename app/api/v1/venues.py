"""Venue-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.database import get_session
from app.core.locale import resolve_locale
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.exceptions import (
    DuplicateVenueNearbyError,
    VenueCategoryNotFoundError,
    VenueNotFoundError,
)
from app.models.user import User
from app.models.venue import Venue
from app.schemas.checkin import CheckinResponse
from app.schemas.venue import NearbyVenueResponse, VenueCreateRequest, VenueResponse
from app.services import checkin as checkin_service
from app.services import venue as venue_service
from app.services import venue_category as venue_category_service

router = APIRouter(prefix="/venues", tags=["venues"])


async def _with_category_names(
    session: AsyncSession, venues: list[Venue], *, locale: str
) -> list[VenueResponse]:
    """Attach each venue's localized category name.

    One catalog lookup per request regardless of how many venues came
    back — the catalog is small and bounded, so fetching it whole beats
    a per-venue join and keeps this off the N+1 path.
    """
    names = await venue_category_service.resolve_names(session, locale)
    return [
        VenueResponse.model_validate(venue).model_copy(
            update={"category_name": names.get(venue.category_id)}
        )
        for venue in venues
    ]


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
    q: str | None = Query(
        default=None, description="Word-similarity venue name search query"
    ),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    locale: str = Depends(resolve_locale),
    session: AsyncSession = Depends(get_session),
) -> list[VenueResponse]:
    """List venues, or search by name when `q` is given."""
    if q is not None:
        venues = await venue_service.search_venues(
            session, q, limit=limit, offset=offset
        )
    else:
        venues = await venue_service.list_venues(session, limit=limit, offset=offset)

    return await _with_category_names(session, venues, locale=locale)


@router.get("/{venue_id}")
async def get_venue(
    venue_id: UUID,
    locale: str = Depends(resolve_locale),
    session: AsyncSession = Depends(get_session),
) -> VenueResponse:
    """Return a single venue by id."""
    try:
        venue = await venue_service.get_venue(session, venue_id)
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found"
        ) from e

    responses = await _with_category_names(session, [venue], locale=locale)
    return responses[0]


@router.get("/{venue_id}/checkins")
async def list_venue_checkins(
    venue_id: UUID,
    viewer: User | None = Depends(get_optional_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CheckinResponse]:
    """List a venue's check-ins, newest first. Private check-ins only
    appear for their own owner or an admin.
    """
    checkins = await checkin_service.list_checkins_for_venue(
        session, venue_id, viewer=viewer, limit=limit, offset=offset
    )
    return [CheckinResponse.model_validate(checkin) for checkin in checkins]
