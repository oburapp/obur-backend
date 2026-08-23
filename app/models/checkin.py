"""CHECKIN model — a user's visit to a venue: its four venue-level
ratings, a note, and a photo.

The four criteria (taste, service, ambiance, value) are all required, so
every check-in contributes exactly the same four data points to the
venue's aggregate and weighs the same as every other. `rating_taste` is
the only field measuring the food itself, and `rating_value` is the only
one measuring price — the others say nothing about what a visit cost.
See ADR-0011 in obur-docs.

`visibility` (see app.core.visibility.Visibility) is the only
visibility control — see the PDD's Check-in Flow section and ADR-0006
in obur-docs. It gates both feed visibility and inclusion in aggregate
rating calculations; there is deliberately no separate toggle for the
latter (see docs/roadmap.md Phase 3). `LIST` and `VENUE_SAVE` use the
same three tiers and the same authorization check
(`app.core.authz.can_view`).

Deletion is soft (`deleted_at`), not a real `DELETE`, so a check-in that
already contributed to an awarded badge or an aggregate rating doesn't
retroactively corrupt that history when a user removes it later. See
app/core/authz.py for who may delete, and how.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
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
from app.core.visibility import Visibility
from app.models.base import Base

# The four venue-level criteria, in the order the check-in flow presents
# them (see the PDD's Check-in Flow, Step 2). Named here once so the
# range constraint below can't drift out of sync with the columns.
_RATING_COLUMNS = (
    "rating_taste",
    "rating_service",
    "rating_ambiance",
    "rating_value",
)

_DEFAULT_VISIBILITY = Visibility.PUBLIC
_ALLOWED_VISIBILITIES = (
    Visibility.PUBLIC,
    Visibility.CLOSE_FRIENDS,
    Visibility.PRIVATE,
)


class Checkin(Base):
    """A single visit: who, where, and (optionally) how it went."""

    __tablename__ = "checkins"
    __table_args__ = (
        *(
            CheckConstraint(
                f"{column} BETWEEN {MIN_RATING} AND {MAX_RATING}",
                name=f"ck_checkins_{column}_range",
            )
            for column in _RATING_COLUMNS
        ),
        CheckConstraint(
            "visibility IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_VISIBILITIES)
            + ")",
            name="ck_checkins_visibility_allowed",
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
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    # Food and drink quality.
    rating_taste: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_service: Mapped[int] = mapped_column(Integer, nullable=False)
    # Atmosphere: music, lighting, decor.
    rating_ambiance: Mapped[int] = mapped_column(Integer, nullable=False)
    # Value for money — is it worth what it costs. Deliberately a price
    # judgement and nothing else: an earlier definition ("the payoff of
    # the overall experience") overlapped the other three once each was
    # rated separately, leaving nothing it alone could express.
    rating_value: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Plain URL, no upload mechanism yet — R2 upload lands in Phase 15
    # (docs/roadmap.md). Same "field exists, integration deferred"
    # pattern as Venue.google_places_id (see ADR-0002 in obur-docs).
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_VISIBILITY
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
