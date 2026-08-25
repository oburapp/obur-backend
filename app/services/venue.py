"""Venue domain: creation with duplicate detection, lookup, and search."""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import WGS84_SRID
from app.core.search import MIN_NAME_SIMILARITY
from app.core.visibility import Visibility
from app.exceptions import (
    DuplicateVenueNearbyError,
    VenueCategoryNotFoundError,
    VenueNotEligibleForVerificationError,
    VenueNotFoundError,
)
from app.models.checkin import Checkin
from app.models.venue import Venue
from app.models.venue_category import VenueCategory

# Radius within which a newly submitted venue is treated as a possible
# duplicate of an existing one — see the PDD's "Venue Identity" section.
_DUPLICATE_RADIUS_METERS = 50

# ADR-0009's verification thresholds. `_MIN_CHECKINS_FOR_AUTO_VERIFICATION`
# (N) applies when a venue has a `google_places_id`: enough independent
# check-ins alone verify it, no admin needed. Without one,
# `_MIN_CHECKINS_FOR_ADMIN_VERIFICATION` (M) only makes a venue *eligible*
# for an admin to confirm via `verify_venue_by_admin`, it doesn't verify
# it by itself. Decided during Phase 9 planning: N is lower than M because
# a Google match is itself a corroborating signal check-ins only add to,
# while the no-match case has nothing but community activity to go on.
_MIN_CHECKINS_FOR_AUTO_VERIFICATION = 3
_MIN_CHECKINS_FOR_ADMIN_VERIFICATION = 5


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


async def find_venue_by_google_places_id(
    session: AsyncSession, google_places_id: str
) -> Venue | None:
    """Return the venue already carrying this exact Google Places
    identity, if any. See `uq_venues_google_places_id`'s partial unique
    index (migration `f7514fe63beb`): at most one venue can ever match.
    """
    result = await session.execute(
        select(Venue).where(Venue.google_places_id == google_places_id)
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
    district: str,
    address_note: str | None = None,
    google_places_id: str | None = None,
    city: str | None = None,
    country_code: str | None = None,
    timezone: str | None = None,
    confirm_duplicate: bool = False,
) -> Venue:
    """Create a venue, or resolve to an existing one.

    Raises `VenueCategoryNotFoundError` if `category_id` doesn't exist.

    Duplicate detection is two layers, per ADR-0009 in obur-docs:

    1. An exact `google_places_id` match is a certain duplicate, Google's
       own identity says so, not a coordinate estimate. Resolves to the
       existing venue idempotently and is **not** bypassable via
       `confirm_duplicate`, there's nothing to confirm, it's the same
       business by definition.
    2. Only once that layer clears: the existing 50-metre `ST_DWithin`
       fallback for everything without a matching `google_places_id` (or
       with none at all). Raises `DuplicateVenueNearbyError` unless
       `confirm_duplicate` is set, callers should surface that as a
       "did you mean this one?" prompt and let the user resubmit with
       `confirm_duplicate=True` if it's genuinely a different venue
       (e.g. a different floor of the same mall).
    """
    if await session.get(VenueCategory, category_id) is None:
        raise VenueCategoryNotFoundError(f"category not found: {category_id}")

    if google_places_id is not None:
        existing = await find_venue_by_google_places_id(session, google_places_id)
        if existing is not None:
            return existing

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
        district=district,
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


async def evaluate_venue_verification(
    session: AsyncSession, venue_id: uuid.UUID
) -> None:
    """Auto-verify a venue if it now qualifies, per ADR-0009's Google-match
    path. Called synchronously from check-in creation, one extra query, not
    a general-purpose evaluation engine (that architecture question belongs
    to Badges, which has a much wider variety of trigger conditions).

    A venue with no `google_places_id` is never touched here: reaching
    `_MIN_CHECKINS_FOR_ADMIN_VERIFICATION` only makes it *eligible*, an
    admin still has to confirm it via `verify_venue_by_admin`.

    Goes through `rls_verify_venue_if_eligible` (a `SECURITY DEFINER`
    function, see migration `f7514fe63beb`) rather than a plain
    `UPDATE venues ...`: the caller here is an ordinary user's own
    check-in, and `venues_update`'s RLS policy is admin-only. The function
    re-checks eligibility itself before writing anything, so passing a
    wrong or stale count from here can't force an unearned verification.
    """
    await session.execute(
        text(
            "SELECT rls_verify_venue_if_eligible(:venue_id, :min_checkins)"
        ).bindparams(
            venue_id=venue_id, min_checkins=_MIN_CHECKINS_FOR_AUTO_VERIFICATION
        )
    )

    # The update above is raw SQL, invisible to the ORM's identity map.
    # If a `Venue` with this id is already loaded in this session (the
    # normal case: the caller just created the checkin's venue, or looked
    # it up), it's now silently stale. `populate_existing=True` forces
    # this query to overwrite it with what the database actually has,
    # rather than the cheaper `session.get()`, which would just return
    # the same stale copy without a round trip at all.
    await session.execute(
        select(Venue)
        .where(Venue.id == venue_id)
        .execution_options(populate_existing=True)
    )


async def _count_distinct_public_checkin_users(
    session: AsyncSession, venue_id: uuid.UUID
) -> int:
    """Independent public check-ins are the only ones that count toward
    either verification threshold, the same restriction the aggregate
    rating (PDD §8) already applies, and for the same reason: a
    `close_friends`/`private` check-in is real evidence to whoever made
    it, but letting it feed a platform-wide signal would surface a
    deliberately restricted share's consequence to everyone.
    """
    result = await session.execute(
        select(func.count(func.distinct(Checkin.user_id))).where(
            Checkin.venue_id == venue_id,
            Checkin.visibility == Visibility.PUBLIC,
            Checkin.deleted_at.is_(None),
        )
    )
    return result.scalar_one()


async def verify_venue_by_admin(session: AsyncSession, venue_id: uuid.UUID) -> Venue:
    """Confirm a venue with no `google_places_id`, the admin half of
    ADR-0009's hybrid verification design.

    Raises `VenueNotFoundError` if `venue_id` doesn't exist.

    Raises `VenueNotEligibleForVerificationError` if the venue hasn't
    reached `_MIN_CHECKINS_FOR_ADMIN_VERIFICATION` yet: the threshold is
    a filter that keeps the admin queue limited to venues that already
    show real community traction, not a formality an admin can override
    by calling this endpoint anyway.

    The caller is required to be an admin (see `app.core.authz.require_admin`
    on the route this backs), so, unlike `evaluate_venue_verification`, a
    plain ORM update is enough here: `venues_update`'s RLS policy already
    allows it.
    """
    venue = await get_venue(session, venue_id)
    if venue.is_verified:
        return venue

    count = await _count_distinct_public_checkin_users(session, venue_id)
    if count < _MIN_CHECKINS_FOR_ADMIN_VERIFICATION:
        raise VenueNotEligibleForVerificationError(
            f"venue {venue_id} has {count} independent check-ins, needs "
            f"{_MIN_CHECKINS_FOR_ADMIN_VERIFICATION}"
        )

    venue.is_verified = True
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
