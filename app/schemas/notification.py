"""Schemas for notification resources."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    """Public shape of a Notification."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    actor_id: UUID | None
    target_type: str
    target_id: UUID
    read_at: datetime | None
    created_at: datetime


class UnreadNotificationCountResponse(BaseModel):
    """Response for the unread notification count endpoint."""

    unread_count: int
