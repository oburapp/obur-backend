"""CLOSE_FRIEND model — a manually curated subset of one's followers,
granted access to `visibility="close_friends"` content (see ADR-0006 in
obur-docs).

The composite foreign key to `FOLLOW` does two jobs at once, enforced by
the database rather than application code:
  1. `friend_id` can only be added if they already follow `user_id` —
     the referenced FOLLOW row must exist.
  2. If that FOLLOW row is later deleted (unfollow), this row is
     automatically deleted too (`ON DELETE CASCADE`) — a close friend
     can never outlive the underlying follow relationship.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CloseFriend(Base):
    """`user_id` has added `friend_id` (one of their followers) to their
    close friends.
    """

    __tablename__ = "close_friends"
    __table_args__ = (
        ForeignKeyConstraint(
            ["friend_id", "user_id"],
            ["follows.follower_id", "follows.following_id"],
            ondelete="CASCADE",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    friend_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
