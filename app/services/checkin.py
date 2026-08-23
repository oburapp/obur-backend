"""Checkin domain: creation, privacy-aware lookup/listing, and
soft/hard delete.
"""

import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import (
    can_view,
    close_friend_of_owner_exists,
    ensure_visible_and_owned,
    is_owner_or_admin,
)
from app.core.visibility import Visibility
from app.exceptions import (
    CheckinNotFoundError,
    FutureVisitDateError,
    NotCheckinOwnerError,
    VenueNotFoundError,
)
from app.models.checkin import Checkin
from app.models.user import User, UserRole
from app.models.venue import Venue

# Fields a check-in's owner (or an admin) may change after creation —
# see ADR-0011 in obur-docs.
_EDITABLE_FIELDS = frozenset(
    {
        "rating_taste",
        "rating_service",
        "rating_ambiance",
        "rating_value",
        "note",
        "photo_url",
        "visibility",
        "visited_at",
    }
)


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
    visited_at: date,
    visited_tz: str,
    rating_taste: int,
    rating_service: int,
    rating_ambiance: int,
    rating_value: int,
    note: str | None = None,
    photo_url: str | None = None,
    visibility: str = Visibility.PUBLIC,
) -> Checkin:
    """Create a check-in.

    Raises `VenueNotFoundError` if `venue_id` doesn't exist.
    Raises `FutureVisitDateError` if `visited_at` is in the future for
    the visitor.
    """
    if await session.get(Venue, venue_id) is None:
        raise VenueNotFoundError(f"venue not found: {venue_id}")

    _ensure_visited_at_not_future(visited_at, visited_tz)

    checkin = Checkin(
        user_id=user_id,
        venue_id=venue_id,
        rating_taste=rating_taste,
        rating_service=rating_service,
        rating_ambiance=rating_ambiance,
        rating_value=rating_value,
        note=note,
        photo_url=photo_url,
        visibility=visibility,
        visited_at=visited_at,
        visited_tz=visited_tz,
    )
    session.add(checkin)
    await session.commit()
    await session.refresh(checkin)
    return checkin


async def get_checkin(
    session: AsyncSession, checkin_id: uuid.UUID, *, viewer: User | None
) -> Checkin:
    """Return a check-in by id.

    Raises `CheckinNotFoundError` if it doesn't exist, is soft-deleted,
    or `viewer` isn't allowed to see it per its `visibility` — a hidden
    check-in looks identical to a nonexistent one to anyone else, so its
    existence is never leaked.
    """
    checkin = await session.get(Checkin, checkin_id)
    if checkin is None or checkin.deleted_at is not None:
        raise CheckinNotFoundError(f"checkin not found: {checkin_id}")
    allowed = await can_view(
        session, owner_id=checkin.user_id, visibility=checkin.visibility, viewer=viewer
    )
    if not allowed:
        raise CheckinNotFoundError(f"checkin not found: {checkin_id}")
    return checkin


async def list_checkins_for_venue(
    session: AsyncSession,
    venue_id: uuid.UUID,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[Checkin]:
    """List a venue's check-ins, newest first, filtered to what `viewer`
    is allowed to see (see app.core.authz.can_view) — an admin sees
    everything.
    """
    conditions = [Checkin.venue_id == venue_id, Checkin.deleted_at.is_(None)]
    if viewer is None:
        conditions.append(Checkin.visibility == Visibility.PUBLIC)
    elif viewer.role != UserRole.ADMIN:
        conditions.append(
            or_(
                Checkin.visibility == Visibility.PUBLIC,
                Checkin.user_id == viewer.id,
                and_(
                    Checkin.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(Checkin.user_id, viewer.id),
                ),
            )
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
    """List a user's check-ins, newest first, filtered to what `viewer`
    is allowed to see (see app.core.authz.can_view) — an admin sees
    everything.
    """
    conditions = [Checkin.user_id == target_user_id, Checkin.deleted_at.is_(None)]
    if viewer is None:
        conditions.append(Checkin.visibility == Visibility.PUBLIC)
    elif not is_owner_or_admin(target_user_id, viewer):
        conditions.append(
            or_(
                Checkin.visibility == Visibility.PUBLIC,
                and_(
                    Checkin.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(Checkin.user_id, viewer.id),
                ),
            )
        )
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
    await ensure_visible_and_owned(
        session,
        owner_id=checkin.user_id,
        visibility=checkin.visibility,
        current_user=current_user,
        not_found_error=CheckinNotFoundError,
        not_found_message=f"checkin not found: {checkin_id}",
        not_owner_error=NotCheckinOwnerError,
        not_owner_message=f"user {current_user.id} may not modify checkin {checkin_id}",
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
    await ensure_visible_and_owned(
        session,
        owner_id=checkin.user_id,
        visibility=checkin.visibility,
        current_user=current_user,
        not_found_error=CheckinNotFoundError,
        not_found_message=f"checkin not found: {checkin_id}",
        not_owner_error=NotCheckinOwnerError,
        not_owner_message=f"user {current_user.id} may not delete checkin {checkin_id}",
    )

    checkin.deleted_at = datetime.now(UTC)
    await session.commit()


async def hard_delete_checkin(session: AsyncSession, checkin_id: uuid.UUID) -> None:
    """Permanently delete a check-in.

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
