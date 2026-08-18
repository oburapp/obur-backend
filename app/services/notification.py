"""Notification domain: created synchronously by the action that
triggers it (a follow, a like) — no queue, no separate worker. See
ADR-0008 in obur-docs.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def create_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    actor_id: uuid.UUID | None,
    target_type: str,
    target_id: uuid.UUID,
) -> Notification:
    """Create a notification for `user_id`.

    Callers run this inside the same session as the triggering action
    (e.g. `follow_user`) so the notification and the action it describes
    commit together — never separately.
    """
    notification = Notification(
        user_id=user_id,
        type=type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
    )
    session.add(notification)
    await session.flush()
    return notification


async def list_notifications(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[Notification]:
    """List a user's notifications, newest first."""
    result = await session.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def count_unread_notifications(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Return how many of a user's notifications are unread."""
    result = await session.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )
    return result.scalar_one()


async def mark_all_notifications_read(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    """Mark every one of a user's unread notifications as read."""
    result = await session.execute(
        select(Notification).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)
        )
    )
    now = datetime.now(UTC)
    for notification in result.scalars().all():
        notification.read_at = now
    await session.commit()
