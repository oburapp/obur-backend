"""VenueSave domain: a user's personal relationship to a venue (visited
/ wishlist / favorite). Defaults to private — see
app/models/venue_save.py — but the owner may choose to share it, using
the same three-tier visibility as CHECKIN and LIST.

A real delete, like LIST — no badge or aggregate depends on a venue
save's contents.
"""

import uuid

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
    NotVenueSaveOwnerError,
    VenueNotFoundError,
    VenueSaveNotFoundError,
)
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_save import VenueSave

# Fields a venue save's owner (or an admin) may change after creation.
# `type` and `venue_id` don't change — delete and re-save instead, same
# reasoning as CHECKIN's immutable product set.
_EDITABLE_FIELDS = frozenset({"visibility"})


async def save_venue(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    venue_id: uuid.UUID,
    type: str,
    visibility: str = Visibility.PRIVATE,
) -> VenueSave:
    """Save a venue as visited/wishlist/favorite. Idempotent for the
    same `(user_id, venue_id, type)` — call `update_venue_save` to
    change an existing save's visibility.

    Raises `VenueNotFoundError` if `venue_id` doesn't exist.
    """
    if await session.get(Venue, venue_id) is None:
        raise VenueNotFoundError(f"venue not found: {venue_id}")

    existing = await session.execute(
        select(VenueSave).where(
            VenueSave.user_id == user_id,
            VenueSave.venue_id == venue_id,
            VenueSave.type == type,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    save = VenueSave(
        user_id=user_id, venue_id=venue_id, type=type, visibility=visibility
    )
    session.add(save)
    await session.commit()
    await session.refresh(save)
    return save


async def get_venue_save(
    session: AsyncSession, venue_save_id: uuid.UUID, *, viewer: User | None
) -> VenueSave:
    """Return a venue save by id.

    Raises `VenueSaveNotFoundError` if it doesn't exist, or `viewer`
    isn't allowed to see it per its `visibility`.
    """
    save = await session.get(VenueSave, venue_save_id)
    if save is None:
        raise VenueSaveNotFoundError(f"venue save not found: {venue_save_id}")
    allowed = await can_view(
        session, owner_id=save.user_id, visibility=save.visibility, viewer=viewer
    )
    if not allowed:
        raise VenueSaveNotFoundError(f"venue save not found: {venue_save_id}")
    return save


async def list_venue_saves_for_user(
    session: AsyncSession,
    target_user_id: uuid.UUID,
    *,
    type: str | None = None,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[VenueSave]:
    """List a user's venue saves, newest first, optionally filtered to
    one `type`, filtered to what `viewer` is allowed to see.
    """
    conditions = [VenueSave.user_id == target_user_id]
    if type is not None:
        conditions.append(VenueSave.type == type)
    if viewer is None:
        conditions.append(VenueSave.visibility == Visibility.PUBLIC)
    elif not is_owner_or_admin(target_user_id, viewer):
        conditions.append(
            or_(
                VenueSave.visibility == Visibility.PUBLIC,
                and_(
                    VenueSave.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(VenueSave.user_id, viewer.id),
                ),
            )
        )
    result = await session.execute(
        select(VenueSave)
        .where(*conditions)
        .order_by(VenueSave.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def update_venue_save(
    session: AsyncSession,
    venue_save_id: uuid.UUID,
    *,
    current_user: User,
    updates: dict[str, object],
) -> VenueSave:
    """Update a venue save's editable fields (see `_EDITABLE_FIELDS`).

    Raises `VenueSaveNotFoundError` if it doesn't exist.
    Raises `NotVenueSaveOwnerError` if `current_user` isn't the owner or
    an admin.
    """
    save = await session.get(VenueSave, venue_save_id)
    if save is None:
        raise VenueSaveNotFoundError(f"venue save not found: {venue_save_id}")
    await ensure_visible_and_owned(
        session,
        owner_id=save.user_id,
        visibility=save.visibility,
        current_user=current_user,
        not_found_error=VenueSaveNotFoundError,
        not_found_message=f"venue save not found: {venue_save_id}",
        not_owner_error=NotVenueSaveOwnerError,
        not_owner_message=(
            f"user {current_user.id} may not modify venue save {venue_save_id}"
        ),
    )

    for field in _EDITABLE_FIELDS & updates.keys():
        setattr(save, field, updates[field])

    await session.commit()
    await session.refresh(save)
    return save


async def delete_venue_save(
    session: AsyncSession, venue_save_id: uuid.UUID, *, current_user: User
) -> None:
    """Permanently delete a venue save.

    Raises `VenueSaveNotFoundError` if it doesn't exist.
    Raises `NotVenueSaveOwnerError` if `current_user` isn't the owner or
    an admin.
    """
    save = await session.get(VenueSave, venue_save_id)
    if save is None:
        raise VenueSaveNotFoundError(f"venue save not found: {venue_save_id}")
    await ensure_visible_and_owned(
        session,
        owner_id=save.user_id,
        visibility=save.visibility,
        current_user=current_user,
        not_found_error=VenueSaveNotFoundError,
        not_found_message=f"venue save not found: {venue_save_id}",
        not_owner_error=NotVenueSaveOwnerError,
        not_owner_message=(
            f"user {current_user.id} may not delete venue save {venue_save_id}"
        ),
    )

    await session.delete(save)
    await session.commit()
