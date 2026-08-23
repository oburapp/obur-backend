"""CHECKIN_BOOKMARK model — a user privately saving a check-in for their
own reference. Always private: nobody, including the checkin's owner,
can see who bookmarked it or how many times — see ADR-0006 in
obur-docs. Separate from CheckinLike, which is a semi-public signal.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CheckinBookmark(Base):
    """`user_id` bookmarked `checkin_id`."""

    __tablename__ = "checkin_bookmarks"

    # The leading PK column already serves "show me my bookmarks"
    # (filtered by user_id alone) efficiently — no separate index needed.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    checkin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("checkins.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
