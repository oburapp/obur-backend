"""CHECKIN_MENTION model: a person mentioned in a check-in's note
(ADR-0019 in obur-docs).

Derived from the note's `@[<user_id>]` tokens on every create and edit.
A token whose row is missing (removed after a block, a visibility change,
or a close-friend removal) still sits in the note and is rendered as a
generic placeholder. Only someone who can see the check-in, and who is a
mutual follower of its author, can be mentioned in it.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CheckinMention(Base):
    """`mentioned_user_id` is mentioned in `checkin_id`'s note."""

    __tablename__ = "checkin_mentions"
    __table_args__ = (
        UniqueConstraint(
            "checkin_id",
            "mentioned_user_id",
            name="uq_checkin_mentions_checkin_id_mentioned_user_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checkin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("checkins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mentioned_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
