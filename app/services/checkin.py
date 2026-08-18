"""Checkin domain: create-with-products in one transaction,
privacy-aware lookup/listing, and soft/hard delete.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import is_owner_or_admin
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
from app.models.checkin_product import CheckinProduct
from app.models.product import Product
from app.models.user import User, UserRole
from app.models.venue import Venue

# Fields a check-in's owner (or an admin) may change after creation.
# The product list itself isn't editable here — see docs/roadmap.md
# Phase 3 scope notes.
_EDITABLE_FIELDS = frozenset(
    {
        "rating_service",
        "rating_ambiance",
        "rating_value",
        "note",
        "photo_url",
        "is_public",
        "visited_at",
    }
)


@dataclass(frozen=True)
class ProductRating:
    """One product's rating within a check-in being created."""

    product_id: uuid.UUID
    rating: int


def _ensure_visited_at_not_future(visited_at: date, visited_tz: str) -> None:
    """`visited_at` must not be after the visitor's own local today.

    Compared in `visited_tz`, not the server's timezone — a visitor east
    of UTC (e.g. Istanbul, the platform's primary market) logging a
    visit in their own early morning hours would otherwise be rejected
    just because the server's UTC date hasn't rolled over yet.
    """
    local_today = datetime.now(ZoneInfo(visited_tz)).date()
    if visited_at > local_today:
        raise FutureVisitDateError(
            f"visited_at ({visited_at}) is after today in {visited_tz} ({local_today})"
        )


async def create_checkin(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    venue_id: uuid.UUID,
    products: list[ProductRating],
    visited_at: date,
    visited_tz: str,
    rating_service: int | None = None,
    rating_ambiance: int | None = None,
    rating_value: int | None = None,
    note: str | None = None,
    photo_url: str | None = None,
    is_public: bool = True,
) -> Checkin:
    """Create a check-in and its product ratings in one transaction.

    Raises `VenueNotFoundError` if `venue_id` doesn't exist.
    Raises `EmptyProductListError` if `products` is empty.
    Raises `DuplicateProductRatingError` if a product appears twice.
    Raises `ProductNotAtVenueError` if a product isn't currently
    available at this venue.
    Raises `FutureVisitDateError` if `visited_at` is in the future for
    the visitor.
    """
    if await session.get(Venue, venue_id) is None:
        raise VenueNotFoundError(f"venue not found: {venue_id}")

    if not products:
        raise EmptyProductListError("a check-in must rate at least one product")

    product_ids = [product.product_id for product in products]
    if len(product_ids) != len(set(product_ids)):
        raise DuplicateProductRatingError(
            "the same product cannot be rated twice in one check-in"
        )

    _ensure_visited_at_not_future(visited_at, visited_tz)

    # Excludes products the venue has since stopped offering
    # (Product.is_available=False) — those stay visible on past
    # check-ins but can't be selected for a new one.
    result = await session.execute(
        select(Product.id).where(
            Product.id.in_(product_ids),
            Product.venue_id == venue_id,
            Product.is_available.is_(True),
        )
    )
    available_product_ids = set(result.scalars().all())
    unavailable = set(product_ids) - available_product_ids
    if unavailable:
        raise ProductNotAtVenueError(
            f"products not currently available at venue {venue_id}: {unavailable}"
        )

    checkin = Checkin(
        user_id=user_id,
        venue_id=venue_id,
        rating_service=rating_service,
        rating_ambiance=rating_ambiance,
        rating_value=rating_value,
        note=note,
        photo_url=photo_url,
        is_public=is_public,
        visited_at=visited_at,
        visited_tz=visited_tz,
    )
    session.add(checkin)
    await session.flush()  # assigns checkin.id before the children need it

    for product in products:
        session.add(
            CheckinProduct(
                checkin_id=checkin.id,
                product_id=product.product_id,
                rating=product.rating,
            )
        )

    await session.commit()
    await session.refresh(checkin)
    return checkin


async def get_checkin(
    session: AsyncSession, checkin_id: uuid.UUID, *, viewer: User | None
) -> Checkin:
    """Return a check-in by id.

    Raises `CheckinNotFoundError` if it doesn't exist, is soft-deleted,
    or is private and `viewer` isn't its owner or an admin — a private
    check-in looks identical to a nonexistent one to anyone else, so its
    existence is never leaked.
    """
    checkin = await session.get(Checkin, checkin_id)
    if checkin is None or checkin.deleted_at is not None:
        raise CheckinNotFoundError(f"checkin not found: {checkin_id}")
    if not checkin.is_public and (
        viewer is None or not is_owner_or_admin(checkin.user_id, viewer)
    ):
        raise CheckinNotFoundError(f"checkin not found: {checkin_id}")
    return checkin


async def get_products_for_checkins(
    session: AsyncSession, checkin_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[CheckinProduct]]:
    """Return each check-in's rated products, grouped by `checkin_id`.

    One batched query (`checkin_id IN (...)`) regardless of how many
    `checkin_ids` are passed — callers building a list response must use
    this instead of querying per check-in in a loop, which would be N+1
    (see docs/testing-strategy.md).
    """
    if not checkin_ids:
        return {}

    result = await session.execute(
        select(CheckinProduct).where(CheckinProduct.checkin_id.in_(checkin_ids))
    )
    grouped: dict[uuid.UUID, list[CheckinProduct]] = defaultdict(list)
    for checkin_product in result.scalars().all():
        grouped[checkin_product.checkin_id].append(checkin_product)
    return grouped


async def list_checkins_for_venue(
    session: AsyncSession,
    venue_id: uuid.UUID,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[Checkin]:
    """List a venue's check-ins, newest first.

    A private check-in only appears for its own owner or an admin —
    everyone else sees only public ones.
    """
    conditions = [Checkin.venue_id == venue_id, Checkin.deleted_at.is_(None)]
    if viewer is None:
        conditions.append(Checkin.is_public.is_(True))
    elif viewer.role != UserRole.ADMIN:
        conditions.append(
            or_(Checkin.is_public.is_(True), Checkin.user_id == viewer.id)
        )
    result = await session.execute(
        select(Checkin)
        .where(*conditions)
        .order_by(Checkin.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def list_checkins_for_user(
    session: AsyncSession,
    target_user_id: uuid.UUID,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[Checkin]:
    """List a user's check-ins, newest first.

    Private check-ins are only included when `viewer` is that same user
    or an admin — everyone else sees only public ones.
    """
    conditions = [Checkin.user_id == target_user_id, Checkin.deleted_at.is_(None)]
    sees_private = viewer is not None and is_owner_or_admin(target_user_id, viewer)
    if not sees_private:
        conditions.append(Checkin.is_public.is_(True))
    result = await session.execute(
        select(Checkin)
        .where(*conditions)
        .order_by(Checkin.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def update_checkin(
    session: AsyncSession,
    checkin_id: uuid.UUID,
    *,
    current_user: User,
    updates: dict[str, object],
) -> Checkin:
    """Update editable fields of a check-in (see `_EDITABLE_FIELDS`).

    Raises `CheckinNotFoundError` if it doesn't exist or is soft-deleted.
    Raises `NotCheckinOwnerError` if `current_user` isn't the owner or an
    admin.
    Raises `FutureVisitDateError` if `visited_at` is updated into the
    future for the visitor.
    """
    checkin = await session.get(Checkin, checkin_id)
    if checkin is None or checkin.deleted_at is not None:
        raise CheckinNotFoundError(f"checkin not found: {checkin_id}")
    if not is_owner_or_admin(checkin.user_id, current_user):
        raise NotCheckinOwnerError(
            f"user {current_user.id} may not modify checkin {checkin_id}"
        )

    if "visited_at" in updates:
        _ensure_visited_at_not_future(updates["visited_at"], checkin.visited_tz)  # type: ignore[arg-type]

    for field in _EDITABLE_FIELDS & updates.keys():
        setattr(checkin, field, updates[field])

    await session.commit()
    await session.refresh(checkin)
    return checkin


async def soft_delete_checkin(
    session: AsyncSession, checkin_id: uuid.UUID, *, current_user: User
) -> None:
    """Mark a check-in deleted without removing the row — see
    app/models/checkin.py for why (badges/aggregates already computed
    from it must not retroactively break).

    Raises `CheckinNotFoundError` if it doesn't exist or is already
    deleted.
    Raises `NotCheckinOwnerError` if `current_user` isn't the owner or
    an admin.
    """
    checkin = await session.get(Checkin, checkin_id)
    if checkin is None or checkin.deleted_at is not None:
        raise CheckinNotFoundError(f"checkin not found: {checkin_id}")
    if not is_owner_or_admin(checkin.user_id, current_user):
        raise NotCheckinOwnerError(
            f"user {current_user.id} may not delete checkin {checkin_id}"
        )

    checkin.deleted_at = datetime.now(UTC)
    await session.commit()


async def hard_delete_checkin(session: AsyncSession, checkin_id: uuid.UUID) -> None:
    """Permanently delete a check-in and its product ratings (cascades
    via `checkin_products`' `ON DELETE CASCADE`).

    Admin-only — enforced by the endpoint's `require_admin` dependency,
    not re-checked here. Works on an already soft-deleted check-in too,
    so a soft-deleted row can still be purged.

    Raises `CheckinNotFoundError` if no such check-in exists at all.
    """
    checkin = await session.get(Checkin, checkin_id)
    if checkin is None:
        raise CheckinNotFoundError(f"checkin not found: {checkin_id}")
    await session.delete(checkin)
    await session.commit()
