"""Close friends domain: a manually curated subset of one's own
followers, granted access to `visibility="close_friends"` content (see
ADR-0006 in obur-docs).

`app.models.close_friend.CloseFriend`'s composite foreign key to
`FOLLOW` already enforces "must currently be a follower" and "removed
automatically on unfollow" at the database level — this service's own
pre-check exists only to turn what would otherwise be a raw foreign key
violation into a clean, typed exception.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CloseFriendNotFoundError, NotAFollowerError
from app.models.close_friend import CloseFriend
from app.models.follow import Follow
from app.models.user import User


async def add_close_friend(
    session: AsyncSession, *, user_id: uuid.UUID, friend_id: uuid.UUID
) -> CloseFriend:
    """Add `friend_id` (one of `user_id`'s followers) to `user_id`'s
    close friends. Idempotent.

    Raises `NotAFollowerError` if `friend_id` doesn't currently follow
    `user_id`.
    """
    existing = await session.get(CloseFriend, (user_id, friend_id))
    if existing is not None:
        return existing

    follows_back = await session.get(Follow, (friend_id, user_id))
    if follows_back is None:
        raise NotAFollowerError(f"{friend_id} does not follow {user_id}")

    close_friend = CloseFriend(user_id=user_id, friend_id=friend_id)
    session.add(close_friend)
    await session.commit()
    await session.refresh(close_friend)
    return close_friend


async def remove_close_friend(
    session: AsyncSession, *, user_id: uuid.UUID, friend_id: uuid.UUID
) -> None:
    """Remove `friend_id` from `user_id`'s close friends.

    Raises `CloseFriendNotFoundError` if they aren't currently on it.
    """
    close_friend = await session.get(CloseFriend, (user_id, friend_id))
    if close_friend is None:
        raise CloseFriendNotFoundError(
            f"{friend_id} is not a close friend of {user_id}"
        )
    await session.delete(close_friend)
    await session.commit()


async def list_close_friends(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[User]:
    """List `user_id`'s close friends."""
    result = await session.execute(
        select(User)
        .join(CloseFriend, CloseFriend.friend_id == User.id)
        .where(CloseFriend.user_id == user_id)
        .order_by(CloseFriend.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
