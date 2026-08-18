"""Notification-facing endpoints."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.models.user import User
from app.schemas.notification import (
    NotificationResponse,
    UnreadNotificationCountResponse,
)
from app.services import notification as notification_service

router = APIRouter(prefix="/users/me/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[NotificationResponse]:
    """List the authenticated user's own notifications, newest first."""
    notifications = await notification_service.list_notifications(
        session, current_user.id, limit=limit, offset=offset
    )
    return [
        NotificationResponse.model_validate(notification)
        for notification in notifications
    ]


@router.get("/unread-count")
async def get_unread_notification_count(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UnreadNotificationCountResponse:
    """Return how many of the authenticated user's notifications are unread."""
    count = await notification_service.count_unread_notifications(
        session, current_user.id
    )
    return UnreadNotificationCountResponse(unread_count=count)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Mark every one of the authenticated user's unread notifications as read."""
    await notification_service.mark_all_notifications_read(session, current_user.id)
