"""Like domain: a semi-public social signal on a check-in or a list.
Separate tables per target type (not a shared polymorphic table) for
real foreign-key integrity — see app/models/checkin_like.py.

Liking something you can't see isn't possible: both functions resolve
the target through its own service's `get_*` first, which already
enforces `visibility` (see app.core.authz.can_view) — a private
check-in or list can't be liked by anyone who couldn't view it either.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import LikeNotFoundError
from app.models.checkin_like import CheckinLike
from app.models.list_like import ListLike
from app.models.notification import NotificationTargetType, NotificationType
from app.models.user import User
from app.services import checkin as checkin_service
from app.services import list as list_service
from app.services.notification import create_notification


async def like_checkin(
    session: AsyncSession, checkin_id: uuid.UUID, *, current_user: User
) -> CheckinLike:
    """Like a check-in. Idempotent.

    Raises `CheckinNotFoundError` if it doesn't exist or isn't visible
    to `current_user`.
    """
    checkin = await checkin_service.get_checkin(
        session, checkin_id, viewer=current_user
    )

    existing = await session.get(CheckinLike, (current_user.id, checkin_id))
    if existing is not None:
        return existing

    like = CheckinLike(user_id=current_user.id, checkin_id=checkin_id)
    session.add(like)
    if checkin.user_id != current_user.id:
        await create_notification(
            session,
            user_id=checkin.user_id,
            type=NotificationType.CHECKIN_LIKE,
            actor_id=current_user.id,
            target_type=NotificationTargetType.CHECKIN,
            target_id=checkin_id,
        )
    await session.commit()
    await session.refresh(like)
    return like


async def unlike_checkin(
    session: AsyncSession, checkin_id: uuid.UUID, *, current_user: User
) -> None:
    """Un-like a check-in.

    Raises `LikeNotFoundError` if it wasn't liked.
    """
    like = await session.get(CheckinLike, (current_user.id, checkin_id))
    if like is None:
        raise LikeNotFoundError(
            f"user {current_user.id} has not liked checkin {checkin_id}"
        )
    await session.delete(like)
    await session.commit()


async def count_checkin_likes(session: AsyncSession, checkin_id: uuid.UUID) -> int:
    """Return how many users have liked a check-in."""
    result = await session.execute(
        select(func.count(CheckinLike.user_id)).where(
            CheckinLike.checkin_id == checkin_id
        )
    )
    return result.scalar_one()


async def like_list(
    session: AsyncSession, list_id: uuid.UUID, *, current_user: User
) -> ListLike:
    """Like a list. Idempotent.

    Raises `ListNotFoundError` if it doesn't exist or isn't visible to
    `current_user`.
    """
    venue_list = await list_service.get_list(session, list_id, viewer=current_user)

    existing = await session.get(ListLike, (current_user.id, list_id))
    if existing is not None:
        return existing

    like = ListLike(user_id=current_user.id, list_id=list_id)
    session.add(like)
    if venue_list.user_id != current_user.id:
        await create_notification(
            session,
            user_id=venue_list.user_id,
            type=NotificationType.LIST_LIKE,
            actor_id=current_user.id,
            target_type=NotificationTargetType.LIST,
            target_id=list_id,
        )
    await session.commit()
    await session.refresh(like)
    return like


async def unlike_list(
    session: AsyncSession, list_id: uuid.UUID, *, current_user: User
) -> None:
    """Un-like a list.

    Raises `LikeNotFoundError` if it wasn't liked.
    """
    like = await session.get(ListLike, (current_user.id, list_id))
    if like is None:
        raise LikeNotFoundError(f"user {current_user.id} has not liked list {list_id}")
    await session.delete(like)
    await session.commit()


async def count_list_likes(session: AsyncSession, list_id: uuid.UUID) -> int:
    """Return how many users have liked a list."""
    result = await session.execute(
        select(func.count(ListLike.user_id)).where(ListLike.list_id == list_id)
    )
    return result.scalar_one()
