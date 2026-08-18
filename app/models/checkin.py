"""CHECKIN model — a user's visit to a venue: optional venue-level
ratings, a note, a photo, and the products logged during the visit (see
CheckinProduct in app/models/checkin_product.py).

`is_public` is the only visibility control — see the PDD's Check-in
Flow section. It gates both feed visibility and inclusion in aggregate
rating calculations; there is deliberately no separate toggle for the
latter (see docs/roadmap.md Phase 3).

Deletion is soft (`deleted_at`), not a real `DELETE`, so a check-in that
already contributed to an awarded badge or an aggregate rating doesn't
retroactively corrupt that history when a user removes it later. See
app/core/authz.py for who may delete, and how.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ratings import MAX_RATING, MIN_RATING
from app.models.base import Base

_DEFAULT_IS_PUBLIC = True


class Checkin(Base):
    """A single visit: who, where, and (optionally) how it went."""

    __tablename__ = "checkins"
    __table_args__ = tuple(
        CheckConstraint(
            f"{column} IS NULL OR {column} BETWEEN {MIN_RATING} AND {MAX_RATING}",
            name=f"ck_checkins_{column}_range",
        )
        for column in ("rating_service", "rating_ambiance", "rating_value")
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
    rating_service: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_ambiance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Plain URL, no upload mechanism yet — R2 upload lands in Phase 7
    # (docs/roadmap.md). Same "field exists, integration deferred"
    # pattern as Venue.google_places_id (see ADR-0002 in obur-docs).
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=_DEFAULT_IS_PUBLIC
    )
    visited_at: Mapped[date] = mapped_column(Date, nullable=False)
    visited_tz: Mapped[str] = mapped_column(String, nullable=False)
    # Soft-delete marker. Not enforced at the DB level via a future-date
    # check on visited_at — "today" depends on the visitor's own
    # timezone (visited_tz), not the server's, so that validation lives
    # in app.services.checkin instead.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
