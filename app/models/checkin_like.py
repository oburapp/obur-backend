"""CHECKIN_LIKE model — a user liking a check-in. Separate from
CheckinBookmark: a like is a semi-public social signal, a bookmark is a
private personal note (see ADR-0006 in obur-docs).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CheckinLike(Base):
    """`user_id` likes `checkin_id`."""

    __tablename__ = "checkin_likes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    # Indexed on its own (not just as the PK's trailing column) — the
    # common query is "who/how many liked this checkin", filtered by
    # checkin_id alone.
    checkin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("checkins.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
