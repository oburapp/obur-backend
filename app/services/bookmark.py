"""Bookmark domain: a private personal note on a check-in or list —
never a social signal. No notification is sent, and there is
deliberately no "count how many bookmarked this" function anywhere in
this module — nobody but the bookmarker themselves can ever see it (see
ADR-0006 in obur-docs).

Bookmarking something you can't see isn't possible — see
app.services.like's module docstring for why; the same reasoning
applies here via the same `get_checkin`/`get_list` calls.

Listing bookmarks re-checks visibility at read time, not just at
bookmark time: if a check-in or list the user bookmarked is later made
private by its owner, it silently drops out of "my bookmarks" too, even
though the bookmark row itself still exists — the bookmark never
outlives the visibility grant that made it possible in the first place.
"""

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import close_friend_of_owner_exists
from app.core.visibility import Visibility
from app.exceptions import BookmarkNotFoundError
from app.models.checkin import Checkin
from app.models.checkin_bookmark import CheckinBookmark
from app.models.list import List
from app.models.list_bookmark import ListBookmark
from app.models.user import User
from app.services import checkin as checkin_service
from app.services import list as list_service


async def bookmark_checkin(
    session: AsyncSession, checkin_id: uuid.UUID, *, current_user: User
) -> CheckinBookmark:
    """Bookmark a check-in. Idempotent.

    Raises `CheckinNotFoundError` if it doesn't exist or isn't visible
    to `current_user`.
    """
    await checkin_service.get_checkin(session, checkin_id, viewer=current_user)

    existing = await session.get(CheckinBookmark, (current_user.id, checkin_id))
    if existing is not None:
        return existing

    bookmark = CheckinBookmark(user_id=current_user.id, checkin_id=checkin_id)
    session.add(bookmark)
    await session.commit()
    await session.refresh(bookmark)
    return bookmark


async def unbookmark_checkin(
    session: AsyncSession, checkin_id: uuid.UUID, *, current_user: User
) -> None:
    """Remove a check-in bookmark.

    Raises `BookmarkNotFoundError` if it wasn't bookmarked.
    """
    bookmark = await session.get(CheckinBookmark, (current_user.id, checkin_id))
    if bookmark is None:
        raise BookmarkNotFoundError(
            f"user {current_user.id} has not bookmarked checkin {checkin_id}"
        )
    await session.delete(bookmark)
    await session.commit()


async def list_bookmarked_checkins(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[Checkin]:
    """List the check-ins a user has bookmarked, newest-bookmarked-first
    — filtered to what's still visible to `user_id` (see module
    docstring). Callers only ever pass their own `current_user.id` here
    — see app/api/v1 for the endpoint that enforces this.
    """
    result = await session.execute(
        select(Checkin)
        .join(CheckinBookmark, CheckinBookmark.checkin_id == Checkin.id)
        .where(
            CheckinBookmark.user_id == user_id,
            Checkin.deleted_at.is_(None),
            or_(
                Checkin.visibility == Visibility.PUBLIC,
                Checkin.user_id == user_id,
                and_(
                    Checkin.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(Checkin.user_id, user_id),
                ),
            ),
        )
        .order_by(CheckinBookmark.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def bookmark_list(
    session: AsyncSession, list_id: uuid.UUID, *, current_user: User
) -> ListBookmark:
    """Bookmark a list. Idempotent.

    Raises `ListNotFoundError` if it doesn't exist or isn't visible to
    `current_user`.
    """
    await list_service.get_list(session, list_id, viewer=current_user)

    existing = await session.get(ListBookmark, (current_user.id, list_id))
    if existing is not None:
        return existing

    bookmark = ListBookmark(user_id=current_user.id, list_id=list_id)
    session.add(bookmark)
    await session.commit()
    await session.refresh(bookmark)
    return bookmark


async def unbookmark_list(
    session: AsyncSession, list_id: uuid.UUID, *, current_user: User
) -> None:
    """Remove a list bookmark.

    Raises `BookmarkNotFoundError` if it wasn't bookmarked.
    """
    bookmark = await session.get(ListBookmark, (current_user.id, list_id))
    if bookmark is None:
        raise BookmarkNotFoundError(
            f"user {current_user.id} has not bookmarked list {list_id}"
        )
    await session.delete(bookmark)
    await session.commit()


async def list_bookmarked_lists(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[List]:
    """List the lists a user has bookmarked, newest-bookmarked-first —
    filtered to what's still visible to `user_id` (see module
    docstring). Callers only ever pass their own `current_user.id` here
    — see app/api/v1 for the endpoint that enforces this.
    """
    result = await session.execute(
        select(List)
        .join(ListBookmark, ListBookmark.list_id == List.id)
        .where(
            ListBookmark.user_id == user_id,
            or_(
                List.visibility == Visibility.PUBLIC,
                List.user_id == user_id,
                and_(
                    List.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(List.user_id, user_id),
                ),
            ),
        )
        .order_by(ListBookmark.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
