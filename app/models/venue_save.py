"""VENUE_SAVE model — a user's relationship to a venue: been / want to go /
favorite.

Defaults to private, unlike `CHECKIN`/`LIST` which default to public —
saving a venue is a personal tracking action first; the owner can still
choose to share it (see app.core.visibility.Visibility) if they want it
to double as a profile showcase.
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.visibility import Visibility
from app.models.base import Base

_DEFAULT_VISIBILITY = Visibility.PRIVATE
_ALLOWED_VISIBILITIES = (
    Visibility.PUBLIC,
    Visibility.CLOSE_FRIENDS,
    Visibility.PRIVATE,
)


class VenueSaveType:
    """Allowed values for `VenueSave.type`."""

    VISITED = "visited"
    WISHLIST = "wishlist"
    FAVORITE = "favorite"


_ALLOWED_TYPES = (
    VenueSaveType.VISITED,
    VenueSaveType.WISHLIST,
    VenueSaveType.FAVORITE,
)

# PEP 586 only allows literal expressions (not attribute references) as
# `Literal[...]` arguments — see app.core.visibility.VisibilityValue for
# the same constraint. Kept in sync with `VenueSaveType` by
# `test_venue_save_type_literal_matches_class`.
VenueSaveTypeValue = Literal["visited", "wishlist", "favorite"]


class VenueSave(Base):
    """A user saving a venue as visited, wishlisted, or favorited."""

    __tablename__ = "venue_saves"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "venue_id", "type", name="uq_venue_saves_user_venue_type"
        ),
        CheckConstraint(
            "visibility IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_VISIBILITIES)
            + ")",
            name="ck_venue_saves_visibility_allowed",
        ),
        CheckConstraint(
            "type IN (" + ", ".join(f"'{value}'" for value in _ALLOWED_TYPES) + ")",
            name="ck_venue_saves_type_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_VISIBILITY
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
