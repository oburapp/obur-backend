"""FOLLOW model — one-directional social relationship, no mutual
approval required (see the PDD's Social Graph section).

Deletable by either side of the relationship: the follower unfollowing,
or the followed user removing a follower — both are just "delete this
row," the only difference is which party is authorized to do it (see
app/services/follow.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Follow(Base):
    """`follower_id` follows `following_id`."""

    __tablename__ = "follows"
    __table_args__ = (
        CheckConstraint(
            "follower_id != following_id", name="ck_follows_no_self_follow"
        ),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    following_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
