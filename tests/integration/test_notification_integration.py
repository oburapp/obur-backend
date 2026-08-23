"""Integration tests for app.services.notification against the real test
database.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationTargetType, NotificationType
from app.models.user import User
from app.services import notification as notification_service


async def _create_user(session: AsyncSession) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    session.add(user)
    await session.flush()
    return user


async def test_create_notification_is_immediately_visible_in_the_same_transaction(
    db_session: AsyncSession,
) -> None:
    recipient = await _create_user(db_session)
    actor = await _create_user(db_session)

    await notification_service.create_notification(
        db_session,
        user_id=recipient.id,
        type=NotificationType.NEW_FOLLOWER,
        actor_id=actor.id,
        target_type=NotificationTargetType.USER,
        target_id=actor.id,
    )

    notifications = await notification_service.list_notifications(
        db_session, recipient.id, limit=20, offset=0
    )
    assert len(notifications) == 1
    assert notifications[0].actor_id == actor.id


async def test_list_notifications_orders_newest_first(db_session: AsyncSession) -> None:
    """`func.now()` (`CURRENT_TIMESTAMP`) is fixed for the whole
    transaction in Postgres, not per-statement — and `db_session`'s
    `commit()` only releases a SAVEPOINT, staying in one outer
    transaction (see tests/integration/conftest.py). Two notifications
    created back-to-back in the same test would otherwise get identical
    `created_at` and an arbitrary tie-broken order, so `first`'s
    timestamp is backdated here to make the ordering deterministic —
    this only fakes the *input*, not the `ORDER BY created_at DESC`
    behavior actually under test.
    """
    recipient = await _create_user(db_session)
    actor = await _create_user(db_session)

    first = await notification_service.create_notification(
        db_session,
        user_id=recipient.id,
        type=NotificationType.NEW_FOLLOWER,
        actor_id=actor.id,
        target_type=NotificationTargetType.USER,
        target_id=actor.id,
    )
    first.created_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    second = await notification_service.create_notification(
        db_session,
        user_id=recipient.id,
        type=NotificationType.CHECKIN_LIKE,
        actor_id=actor.id,
        target_type=NotificationTargetType.CHECKIN,
        target_id=uuid4(),
    )
    await db_session.commit()

    notifications = await notification_service.list_notifications(
        db_session, recipient.id, limit=20, offset=0
    )
    assert [n.id for n in notifications] == [second.id, first.id]


async def test_count_unread_notifications_only_counts_unread(
    db_session: AsyncSession,
) -> None:
    recipient = await _create_user(db_session)
    actor = await _create_user(db_session)
    await notification_service.create_notification(
        db_session,
        user_id=recipient.id,
        type=NotificationType.NEW_FOLLOWER,
        actor_id=actor.id,
        target_type=NotificationTargetType.USER,
        target_id=actor.id,
    )
    await db_session.commit()

    before = await notification_service.count_unread_notifications(
        db_session, recipient.id
    )
    await notification_service.mark_all_notifications_read(db_session, recipient.id)
    after = await notification_service.count_unread_notifications(
        db_session, recipient.id
    )

    assert before == 1
    assert after == 0


async def test_mark_all_notifications_read_only_affects_the_given_user(
    db_session: AsyncSession,
) -> None:
    recipient_a = await _create_user(db_session)
    recipient_b = await _create_user(db_session)
    actor = await _create_user(db_session)
    for recipient in (recipient_a, recipient_b):
        await notification_service.create_notification(
            db_session,
            user_id=recipient.id,
            type=NotificationType.NEW_FOLLOWER,
            actor_id=actor.id,
            target_type=NotificationTargetType.USER,
            target_id=actor.id,
        )
    await db_session.commit()

    await notification_service.mark_all_notifications_read(db_session, recipient_a.id)

    unread_a = await notification_service.count_unread_notifications(
        db_session, recipient_a.id
    )
    unread_b = await notification_service.count_unread_notifications(
        db_session, recipient_b.id
    )
    assert unread_a == 0
    assert unread_b == 1


async def test_mark_all_notifications_read_is_idempotent(
    db_session: AsyncSession,
) -> None:
    recipient = await _create_user(db_session)
    actor = await _create_user(db_session)
    await notification_service.create_notification(
        db_session,
        user_id=recipient.id,
        type=NotificationType.NEW_FOLLOWER,
        actor_id=actor.id,
        target_type=NotificationTargetType.USER,
        target_id=actor.id,
    )
    await db_session.commit()

    await notification_service.mark_all_notifications_read(db_session, recipient.id)
    await notification_service.mark_all_notifications_read(db_session, recipient.id)

    unread = await notification_service.count_unread_notifications(
        db_session, recipient.id
    )
    assert unread == 0
