"""VENUE_SAVE model — a user's relationship to a venue: been / want to go /
favorite.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VenueSaveType:
    """Allowed values for `VenueSave.type`."""

    VISITED = "visited"
    WISHLIST = "wishlist"
    FAVORITE = "favorite"


class VenueSave(Base):
    """A user saving a venue as visited, wishlisted, or favorited."""

    __tablename__ = "venue_saves"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
