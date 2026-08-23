"""List contents: adding, moving, and removing the venues inside a list.

Ordering uses fractional indexing (`ListItem.position`, a lexicographically
sortable string — see the `fractional-indexing` package and ADR-0007 in
obur-docs), so moving or inserting an item only ever writes the one row
being changed and never renumbers its neighbours. The column requires
`COLLATE "C"`: the algorithm's correctness rests on byte ordering, which a
locale-aware default collation silently breaks.

Every mutation here is gated by the parent list's own ownership check —
see app/services/list.py, which owns the list itself.
"""

import uuid

import fractional_indexing as fi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import ensure_visible_and_owned
from app.exceptions import (
    DuplicateListItemError,
    ListItemNotFoundError,
    ListNotFoundError,
    NotListOwnerError,
    VenueNotFoundError,
)
from app.models.list import List
from app.models.list_item import ListItem
from app.models.user import User
from app.models.venue import Venue


async def _ordered_items(session: AsyncSession, list_id: uuid.UUID) -> list[ListItem]:
    result = await session.execute(
        select(ListItem).where(ListItem.list_id == list_id).order_by(ListItem.position)
    )
    return list(result.scalars().all())


async def _position_at_end(session: AsyncSession, list_id: uuid.UUID) -> str:
    """Compute a fractional-indexing key that sorts after every one of
    `list_id`'s current items (or the first key, if it has none).
    """
    items = await _ordered_items(session, list_id)
    last = items[-1].position if items else None
    return fi.generate_key_between(last, None)


async def _position_after(
    session: AsyncSession, list_id: uuid.UUID, after_item_id: uuid.UUID | None
) -> str:
    """Compute a fractional-indexing key that sorts right after
    `after_item_id` (or at the very start, if `None`) among `list_id`'s
    current items.

    Raises `ListItemNotFoundError` if `after_item_id` isn't on this list.
    """
    items = await _ordered_items(session, list_id)
    if after_item_id is None:
        following = items[0].position if items else None
        return fi.generate_key_between(None, following)

    for index, item in enumerate(items):
        if item.id == after_item_id:
            following = items[index + 1].position if index + 1 < len(items) else None
            return fi.generate_key_between(item.position, following)

    raise ListItemNotFoundError(f"list item not found: {after_item_id}")


async def add_list_item(
    session: AsyncSession,
    list_id: uuid.UUID,
    *,
    current_user: User,
    venue_id: uuid.UUID,
    after_item_id: uuid.UUID | None = None,
) -> ListItem:
    """Add a venue to a list.

    By default (`after_item_id=None`) it's appended to the end — the
    common case. Pass an existing item's id to insert right after it
    instead.

    Raises `ListNotFoundError` if the list doesn't exist.
    Raises `NotListOwnerError` if `current_user` isn't the owner or an
    admin.
    Raises `VenueNotFoundError` if the venue doesn't exist.
    Raises `DuplicateListItemError` if the venue is already on this list.
    Raises `ListItemNotFoundError` if `after_item_id` isn't on this list.
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
    if await session.get(Venue, venue_id) is None:
        raise VenueNotFoundError(f"venue not found: {venue_id}")

    existing = await session.execute(
        select(ListItem).where(
            ListItem.list_id == list_id, ListItem.venue_id == venue_id
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise DuplicateListItemError(f"venue {venue_id} is already on list {list_id}")

    if after_item_id is None:
        position = await _position_at_end(session, list_id)
    else:
        position = await _position_after(session, list_id, after_item_id)
    item = ListItem(list_id=list_id, venue_id=venue_id, position=position)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def move_list_item(
    session: AsyncSession,
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    current_user: User,
    after_item_id: uuid.UUID | None,
) -> ListItem:
    """Move an item to right after `after_item_id` (or to the very
    start, if `None`) — writes only this one row.

    Raises `ListNotFoundError` if the list doesn't exist.
    Raises `NotListOwnerError` if `current_user` isn't the owner or an
    admin.
    Raises `ListItemNotFoundError` if `item_id` (or `after_item_id`)
    isn't on this list.
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

    item = await session.get(ListItem, item_id)
    if item is None or item.list_id != list_id:
        raise ListItemNotFoundError(f"list item not found: {item_id}")

    item.position = await _position_after(session, list_id, after_item_id)
    await session.commit()
    await session.refresh(item)
    return item


async def remove_list_item(
    session: AsyncSession,
    list_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    current_user: User,
) -> None:
    """Remove an item from a list.

    Raises `ListNotFoundError` if the list doesn't exist.
    Raises `NotListOwnerError` if `current_user` isn't the owner or an
    admin.
    Raises `ListItemNotFoundError` if `item_id` isn't on this list.
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

    item = await session.get(ListItem, item_id)
    if item is None or item.list_id != list_id:
        raise ListItemNotFoundError(f"list item not found: {item_id}")

    await session.delete(item)
    await session.commit()


async def list_items_for_list(
    session: AsyncSession, list_id: uuid.UUID, *, limit: int, offset: int
) -> list[ListItem]:
    """List a list's items in order. Callers are responsible for
    checking `get_list`'s visibility first — this doesn't re-check it.
    """
    result = await session.execute(
        select(ListItem)
        .where(ListItem.list_id == list_id)
        .order_by(ListItem.position)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
