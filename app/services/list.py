"""List domain: a curated collection of venues, and who may see it.

Unlike CHECKIN, deletion is a real delete — no badge or aggregate depends
on list contents (see the PDD's example badges, all of which are
check-in-based).

The list's *contents* live in app/services/list_item.py: adding, moving,
and removing items is a separate concern with its own ordering machinery,
and keeping them apart is what stops either file growing past the length
this repo allows itself.
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
from app.exceptions import ListNotFoundError, NotListOwnerError
from app.models.list import List
from app.models.user import User

# Fields a list's owner (or an admin) may change after creation.
_EDITABLE_FIELDS = frozenset({"title", "description", "visibility"})


async def create_list(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    description: str | None = None,
    visibility: str = Visibility.PUBLIC,
) -> List:
    """Create an empty list."""
    venue_list = List(
        user_id=user_id, title=title, description=description, visibility=visibility
    )
    session.add(venue_list)
    await session.commit()
    await session.refresh(venue_list)
    return venue_list


async def get_list(
    session: AsyncSession, list_id: uuid.UUID, *, viewer: User | None
) -> List:
    """Return a list by id.

    Raises `ListNotFoundError` if it doesn't exist, or `viewer` isn't
    allowed to see it per its `visibility` — see app.core.authz.can_view.
    """
    venue_list = await session.get(List, list_id)
    if venue_list is None:
        raise ListNotFoundError(f"list not found: {list_id}")
    allowed = await can_view(
        session,
        owner_id=venue_list.user_id,
        visibility=venue_list.visibility,
        viewer=viewer,
    )
    if not allowed:
        raise ListNotFoundError(f"list not found: {list_id}")
    return venue_list


async def list_lists_for_user(
    session: AsyncSession,
    target_user_id: uuid.UUID,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[List]:
    """List a user's lists, newest first, filtered to what `viewer` is
    allowed to see (see app.core.authz.can_view) — an admin sees
    everything.
    """
    conditions = [List.user_id == target_user_id]
    if viewer is None:
        conditions.append(List.visibility == Visibility.PUBLIC)
    elif not is_owner_or_admin(target_user_id, viewer):
        conditions.append(
            or_(
                List.visibility == Visibility.PUBLIC,
                and_(
                    List.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(List.user_id, viewer.id),
                ),
            )
        )
    result = await session.execute(
        select(List)
        .where(*conditions)
        .order_by(List.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def update_list(
    session: AsyncSession,
    list_id: uuid.UUID,
    *,
    current_user: User,
    updates: dict[str, object],
) -> List:
    """Update a list's editable fields (see `_EDITABLE_FIELDS`).

    Raises `ListNotFoundError` if it doesn't exist.
    Raises `NotListOwnerError` if `current_user` isn't the owner or an
    admin.
    """
    venue_list = await session.get(List, list_id)
    if venue_list is None:
        raise ListNotFoundError(f"list not found: {list_id}")
    await ensure_visible_and_owned(
        session,
        owner_id=venue_list.user_id,
        visibility=venue_list.visibility,
        current_user=current_user,
        not_found_error=ListNotFoundError,
        not_found_message=f"list not found: {list_id}",
        not_owner_error=NotListOwnerError,
        not_owner_message=f"user {current_user.id} may not modify list {list_id}",
    )

    for field in _EDITABLE_FIELDS & updates.keys():
        setattr(venue_list, field, updates[field])

    await session.commit()
    await session.refresh(venue_list)
    return venue_list


async def delete_list(
    session: AsyncSession, list_id: uuid.UUID, *, current_user: User
) -> None:
    """Permanently delete a list and its items (cascades via
    `list_items`'/`list_likes`'/`list_bookmarks`' `ON DELETE CASCADE`).

    Raises `ListNotFoundError` if it doesn't exist.
    Raises `NotListOwnerError` if `current_user` isn't the owner or an
    admin.
    """
    venue_list = await session.get(List, list_id)
    if venue_list is None:
        raise ListNotFoundError(f"list not found: {list_id}")
    await ensure_visible_and_owned(
        session,
        owner_id=venue_list.user_id,
        visibility=venue_list.visibility,
        current_user=current_user,
        not_found_error=ListNotFoundError,
        not_found_message=f"list not found: {list_id}",
        not_owner_error=NotListOwnerError,
        not_owner_message=f"user {current_user.id} may not delete list {list_id}",
    )

    await session.delete(venue_list)
    await session.commit()
