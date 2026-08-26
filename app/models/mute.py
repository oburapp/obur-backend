"""MUTE model: the lighter counterpart to `BLOCK` (PDD §11). The
relationship, visibility, and discoverability between the two people are
all untouched; only the muting user's own feed stops surfacing the muted
person's content. One-directional and silent, and not derived from
`FOLLOW` unlike `CLOSE_FRIEND`: a user can mute someone they don't
follow, to keep a stranger's content out of an algorithmic feed layer.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Mute(Base):
    """`user_id` has muted `muted_id`."""

    __tablename__ = "mutes"
    __table_args__ = (
        CheckConstraint("user_id != muted_id", name="ck_mutes_no_self_mute"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    muted_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
