"""BLOCK model: one user removing another entirely, in both directions
at once (see ADR-0010 in obur-docs, PDD §11).

Stored directionally, like `FOLLOW`, even though enforcement is
bidirectional: only the blocker may unblock, and the blocked person must
never learn a block exists, both need to know which way it runs. Its own
RLS `SELECT` policy is blocker-only, deliberately stricter than
`FOLLOW`'s or `CLOSE_FRIEND`'s either-party visibility, so every
enforcement check goes through the `rls_is_blocked_pair` SQL function
instead of a plain query, see ADR-0010's "access control" section for
why.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Block(Base):
    """`blocker_id` has blocked `blocked_id`."""

    __tablename__ = "blocks"
    __table_args__ = (
        CheckConstraint("blocker_id != blocked_id", name="ck_blocks_no_self_block"),
    )

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed on its own, for the reverse-direction lookup every
    # bidirectional enforcement check needs (the same role FOLLOW's index
    # on following_id already plays).
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
