"""Mute domain: the lighter counterpart to `Block` (PDD §11).
One-directional, silent, and affects only the muting user's own feed;
nothing about the relationship, visibility, or discoverability between
the two people changes. No retroactive effect either: existing likes,
bookmarks, and notifications are untouched, unlike blocking's purge.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import MuteNotFoundError, SelfMuteError
from app.models.mute import Mute
from app.models.user import User


async def create_mute(
    session: AsyncSession, *, user_id: uuid.UUID, muted_id: uuid.UUID
) -> Mute:
    """Make `user_id` mute `muted_id`. Idempotent: muting someone
    already muted just returns the existing relationship.

    Raises `SelfMuteError` if `user_id == muted_id`.
    """
    if user_id == muted_id:
        raise SelfMuteError("a user cannot mute themselves")

    existing = await session.get(Mute, (user_id, muted_id))
    if existing is not None:
        return existing

    mute = Mute(user_id=user_id, muted_id=muted_id)
    session.add(mute)
    await session.commit()
    await session.refresh(mute)
    return mute


async def remove_mute(
    session: AsyncSession, *, user_id: uuid.UUID, muted_id: uuid.UUID
) -> None:
    """Unmute. Only the muter has any way to reach this, the same trust
    `app.services.block.remove_block` places in its own caller:
    `mutes_delete`'s RLS policy is muter-only, and there is no
    endpoint through which the muted party could ever supply their own
    id as `user_id`.

    Raises `MuteNotFoundError` if the mute doesn't exist.
    """
    mute = await session.get(Mute, (user_id, muted_id))
    if mute is None:
        raise MuteNotFoundError(f"{user_id} has not muted {muted_id}")
    await session.delete(mute)
    await session.commit()


async def list_muted_users(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[User]:
    """List the users `user_id` has muted."""
    result = await session.execute(
        select(User)
        .join(Mute, Mute.muted_id == User.id)
        .where(Mute.user_id == user_id)
        .order_by(Mute.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
