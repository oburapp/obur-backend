"""Ownership-based authorization.

The base rule, for every user-owned resource: you may act on your own
resource. `UserRole.ADMIN` is an override on top of that rule, not a
replacement for it — an admin may act on anyone's resource, a regular
user only their own.

This is deliberately generic (`owner_id`, not "checkin owner") so the
same one-line check is reused as-is once other user-owned resources
(lists, likes) exist — see docs/roadmap.md Phase 4.
"""

import uuid

from fastapi import Depends
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from app.core import problems
from app.core.auth import get_current_user
from app.core.problems import ProblemError
from app.core.visibility import Visibility
from app.models.close_friend import CloseFriend
from app.models.user import User, UserRole, UserStatus


def is_owner_or_admin(owner_id: uuid.UUID, current_user: User) -> bool:
    """Return whether `current_user` may view or modify a resource owned
    by `owner_id` — its own resource, or an admin acting on anyone's.
    Same rule for both: an admin's whole point is to see and act on
    content a regular user couldn't.
    """
    return current_user.id == owner_id or current_user.role == UserRole.ADMIN


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency for admin-only endpoints (e.g. permanently
    deleting a check-in) — raises 403 for a non-admin.
    """
    if current_user.role != UserRole.ADMIN:
        raise ProblemError(problems.ADMIN_REQUIRED)
    return current_user


async def is_close_friend(
    session: AsyncSession, *, owner_id: uuid.UUID, viewer_id: uuid.UUID
) -> bool:
    """Return whether `viewer_id` is on `owner_id`'s close friends list."""
    result = await session.execute(
        select(CloseFriend).where(
            CloseFriend.user_id == owner_id, CloseFriend.friend_id == viewer_id
        )
    )
    return result.scalar_one_or_none() is not None


async def can_view(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    visibility: str,
    viewer: User | None,
) -> bool:
    """Return whether `viewer` may see a resource owned by `owner_id`
    with the given `visibility` — shared by `CHECKIN`, `LIST`, and
    `VENUE_SAVE` (see app.core.visibility.Visibility).

    The owner and any admin can always see it, regardless of
    `visibility`. Otherwise: `public` — anyone; `private` — nobody else;
    `close_friends` — only someone the owner has added to their close
    friends (see app.models.close_friend).
    """
    if viewer is not None and is_owner_or_admin(owner_id, viewer):
        return True
    if visibility == Visibility.PUBLIC:
        return True
    if visibility == Visibility.PRIVATE:
        return False
    if visibility == Visibility.CLOSE_FRIENDS:
        if viewer is None:
            return False
        return await is_close_friend(session, owner_id=owner_id, viewer_id=viewer.id)
    return False


async def ensure_visible_and_owned(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    visibility: str,
    current_user: User,
    not_found_error: type[Exception],
    not_found_message: str,
    not_owner_error: type[Exception],
    not_owner_message: str,
) -> None:
    """Guard a mutation (update/delete) the same way `can_view` guards a
    read: raise `not_found_error` if `current_user` can't even see the
    resource, `not_owner_error` if they can see it but don't own it, or
    return silently if they're the owner or an admin.

    Checking visibility before ownership matters — a stranger PATCHing a
    private checkin's id must get the same 404 a nonexistent id would,
    never a 403 that would confirm the id belongs to something real (see
    `can_view`'s own docstring on this — a hidden resource must look
    identical to a nonexistent one to anyone it's hidden from, whether
    they're reading or writing).
    """
    if is_owner_or_admin(owner_id, current_user):
        return
    visible = await can_view(
        session, owner_id=owner_id, visibility=visibility, viewer=current_user
    )
    if not visible:
        raise not_found_error(not_found_message)
    raise not_owner_error(not_owner_message)


def close_friend_of_owner_exists(
    owner_id_column: InstrumentedAttribute[uuid.UUID], viewer_id: uuid.UUID
) -> ColumnElement[bool]:
    """Correlated subquery: is `viewer_id` a close friend of whoever
    owns the row being filtered (`owner_id_column`, e.g. `Checkin.user_id`)?
    Folds the close-friends visibility check into a single list query
    instead of a per-row lookup (N+1) — shared by every listing query
    that filters on `close_friends` visibility (checkins, lists, venue
    saves, bookmarks of either).
    """
    return (
        select(CloseFriend.user_id)
        .where(
            CloseFriend.user_id == owner_id_column, CloseFriend.friend_id == viewer_id
        )
        .exists()
    )


def account_is_visible(
    owner_id_column: InstrumentedAttribute[uuid.UUID],
) -> ColumnElement[bool]:
    """Correlated subquery: is the account that owns this row still visible
    to other people?

    A frozen or suspended account drops out of everyone else's listings
    (PDD §6, §11). The two are the same to a viewer and differ only in who
    can undo them — freezing is self-service and reverses on the owner's
    next sign-in, suspension is admin-only and never user-reversible.

    Applied as a query condition rather than a post-filter so a listing's
    page size stays honest: filtering after the fact would return short
    pages and let a caller infer that something was removed.

    Uses an alias so the subquery keeps its own `users` reference. Several
    callers already join `User` in the outer query, and without the alias
    SQLAlchemy auto-correlates the inner one away, leaving a subquery with
    no FROM clause at all.
    """
    owner = aliased(User)
    return (
        select(owner.id)
        .where(owner.id == owner_id_column, owner.status == UserStatus.ACTIVE)
        .exists()
    )
