"""LIST_BOOKMARK model — a user privately saving a list for their own
reference. Always private, same reasoning as CheckinBookmark.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ListBookmark(Base):
    """`user_id` bookmarked `list_id`."""

    __tablename__ = "list_bookmarks"

    # The leading PK column already serves "show me my bookmarks"
    # (filtered by user_id alone) efficiently — no separate index needed.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lists.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
