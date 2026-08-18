"""Follow domain: one-directional, no mutual approval. Either side of
the relationship may delete it — the follower unfollowing, or the
followed user removing a follower (see app/api/v1/follows.py).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import FollowNotFoundError, SelfFollowError
from app.models.follow import Follow
from app.models.notification import NotificationTargetType, NotificationType
from app.models.user import User
from app.services.notification import create_notification


async def follow_user(
    session: AsyncSession, *, follower_id: uuid.UUID, following_id: uuid.UUID
) -> Follow:
    """Make `follower_id` follow `following_id`. Idempotent — following
    someone already followed just returns the existing relationship.

    Raises `SelfFollowError` if `follower_id == following_id`.
    """
    if follower_id == following_id:
        raise SelfFollowError("a user cannot follow themselves")

    existing = await session.get(Follow, (follower_id, following_id))
    if existing is not None:
        return existing

    follow = Follow(follower_id=follower_id, following_id=following_id)
    session.add(follow)
    await create_notification(
        session,
        user_id=following_id,
        type=NotificationType.NEW_FOLLOWER,
        actor_id=follower_id,
        target_type=NotificationTargetType.USER,
        target_id=follower_id,
    )
    await session.commit()
    await session.refresh(follow)
    return follow


async def unfollow_user(
    session: AsyncSession, *, follower_id: uuid.UUID, following_id: uuid.UUID
) -> None:
    """Make `follower_id` stop following `following_id` — a real delete.

    Raises `FollowNotFoundError` if the relationship doesn't exist.
    """
    follow = await session.get(Follow, (follower_id, following_id))
    if follow is None:
        raise FollowNotFoundError(f"{follower_id} does not follow {following_id}")
    await session.delete(follow)
    await session.commit()


async def remove_follower(
    session: AsyncSession, *, user_id: uuid.UUID, follower_id: uuid.UUID
) -> None:
    """Remove `follower_id` from `user_id`'s own followers — the same
    row `unfollow_user` would delete, but initiated by the other side of
    the relationship.

    Raises `FollowNotFoundError` if `follower_id` doesn't currently
    follow `user_id`.
    """
    await unfollow_user(session, follower_id=follower_id, following_id=user_id)


async def list_followers(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[User]:
    """List the users who follow `user_id`."""
    result = await session.execute(
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.following_id == user_id)
        .order_by(Follow.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def list_following(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[User]:
    """List the users `user_id` follows."""
    result = await session.execute(
        select(User)
        .join(Follow, Follow.following_id == User.id)
        .where(Follow.follower_id == user_id)
        .order_by(Follow.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
