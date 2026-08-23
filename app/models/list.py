"""LIST model — a curated collection of venues (e.g. "date night spots"),
not a log of visits. See app/models/list_item.py for its contents and
app/models/checkin.py's module docstring for the shared visibility model
(`LIST` uses the same three tiers as `CHECKIN` and `VENUE_SAVE`).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.visibility import Visibility
from app.models.base import Base

_DEFAULT_VISIBILITY = Visibility.PUBLIC
_ALLOWED_VISIBILITIES = (
    Visibility.PUBLIC,
    Visibility.CLOSE_FRIENDS,
    Visibility.PRIVATE,
)


class List(Base):
    """A user-curated collection of venues."""

    __tablename__ = "lists"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_VISIBILITIES)
            + ")",
            name="ck_lists_visibility_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_VISIBILITY
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
