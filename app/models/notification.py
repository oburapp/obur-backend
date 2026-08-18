"""NOTIFICATION model — a record of something the recipient should know
about (new follower, a like on their check-in or list). Created
synchronously, in the same transaction as the event that triggers it —
no queue, no separate worker (see ADR-0008 in obur-docs).

`read_at` lives here, not on the client, so "read" state is the same
across every device the recipient uses — the whole point of putting
this in the backend instead of tracking it locally per app.

`target_type`/`target_id` deliberately isn't a real foreign key: a
notification can point at a check-in, a list, or (later) a badge, and a
notification is a transient, denormalized record, not data other
correctness depends on — unlike CheckinBookmark/CheckinLike, where
losing referential integrity would be a real problem, see those models.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationType:
    """Allowed values for `Notification.type`."""

    NEW_FOLLOWER = "new_follower"
    CHECKIN_LIKE = "checkin_like"
    LIST_LIKE = "list_like"


class NotificationTargetType:
    """Allowed values for `Notification.target_type`."""

    CHECKIN = "checkin"
    LIST = "list"
    # For NEW_FOLLOWER: target_id is the follower's own user id (the
    # notification is "about" the person who followed you).
    USER = "user"


class Notification(Base):
    """A single notification for its `user_id` recipient."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    # Who did it — nullable for a future system-generated notification
    # type (e.g. a badge award) with no acting user.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
