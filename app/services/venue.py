"""Venue domain: creation with duplicate detection, lookup, and search."""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import WGS84_SRID
from app.core.search import MIN_NAME_SIMILARITY
from app.exceptions import (
    DuplicateVenueNearbyError,
    VenueCategoryNotFoundError,
    VenueNotFoundError,
)
from app.models.venue import Venue
from app.models.venue_category import VenueCategory

# Radius within which a newly submitted venue is treated as a possible
# duplicate of an existing one — see the PDD's "Venue Identity" section.
_DUPLICATE_RADIUS_METERS = 50


async def find_nearby_venue(
    session: AsyncSession, lat: float, lng: float
) -> Venue | None:
    """Return an existing venue within `_DUPLICATE_RADIUS_METERS` of
    `(lat, lng)`, if any.
    """
    point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), WGS84_SRID)
    result = await session.execute(
        select(Venue)
        .where(func.ST_DWithin(Venue.location, point, _DUPLICATE_RADIUS_METERS))
        .limit(1)
    )
    return result.scalars().first()


async def create_venue(
    session: AsyncSession,
    *,
    name: str,
    lat: float,
    lng: float,
    category_id: uuid.UUID,
    added_by: uuid.UUID,
    address_note: str | None = None,
    google_places_id: str | None = None,
    city: str | None = None,
    country_code: str | None = None,
    timezone: str | None = None,
    confirm_duplicate: bool = False,
) -> Venue:
    """Create a venue.

    Raises `VenueCategoryNotFoundError` if `category_id` doesn't exist.

    Raises `DuplicateVenueNearbyError` if an existing venue is within
    `_DUPLICATE_RADIUS_METERS` of the given coordinates, unless
    `confirm_duplicate` is set — callers should surface the first error as
    a "did you mean this one?" prompt (per the PDD) and let the user
    resubmit with `confirm_duplicate=True` if it's genuinely a different
    venue (e.g. a different floor of the same mall).
    """
    if await session.get(VenueCategory, category_id) is None:
        raise VenueCategoryNotFoundError(f"category not found: {category_id}")

    if not confirm_duplicate:
        nearby = await find_nearby_venue(session, lat, lng)
        if nearby is not None:
            raise DuplicateVenueNearbyError(nearby.id)

    venue = Venue(
        name=name,
        lat=lat,
        lng=lng,
        category_id=category_id,
        added_by=added_by,
        address_note=address_note,
        google_places_id=google_places_id,
        city=city,
        country_code=country_code,
        timezone=timezone,
    )
    session.add(venue)
    await session.commit()
    await session.refresh(venue)
    return venue


async def get_venue(session: AsyncSession, venue_id: uuid.UUID) -> Venue:
    """Return a venue by id.

    Raises `VenueNotFoundError` if no such venue exists.
    """
    venue = await session.get(Venue, venue_id)
    if venue is None:
        raise VenueNotFoundError(f"venue not found: {venue_id}")
    return venue


async def list_venues(session: AsyncSession, *, limit: int, offset: int) -> list[Venue]:
    """Return venues ordered newest-first, paginated."""
    result = await session.execute(
        select(Venue).order_by(Venue.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def search_venues(
    session: AsyncSession, query: str, *, limit: int, offset: int
) -> list[Venue]:
    """Search venues by name using `pg_trgm` word-similarity matching —
    language-agnostic and typo-tolerant, unlike linguistic full-text
    search. See ADR-0003 in obur-docs and `app.core.search`.

    Diacritics are folded on both sides via `immutable_unaccent()` (see
    migration `ed402e8663f4`) so e.g. "doner" matches "Döner".
    """
    # SET LOCAL doesn't accept bind parameters (a PostgreSQL protocol
    # limitation, verified directly against the driver) — safe to inline
    # here since MIN_NAME_SIMILARITY is a fixed internal constant, never
    # user input. Scoped to this transaction only, so it can't leak onto
    # a pooled connection reused by a later, unrelated request.
    await session.execute(
        text(f"SET LOCAL pg_trgm.word_similarity_threshold = {MIN_NAME_SIMILARITY}")
    )

    unaccented_query = func.immutable_unaccent(query)
    unaccented_name = func.immutable_unaccent(Venue.name)
    result = await session.execute(
        select(Venue)
        .where(unaccented_query.op("<%")(unaccented_name))
        .order_by(func.word_similarity(unaccented_query, unaccented_name).desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
