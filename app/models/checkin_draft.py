"""CHECKIN_DRAFT model: an in-progress check-in, server-synced so it can
be resumed on any device (PDD §17, ADR-0018 in obur-docs).

A separate table rather than a `Checkin.is_draft` flag, so a draft can
never leak into an aggregate, badge, or feed query by a query forgetting
to filter it out. Every content field is nullable because a draft is
incomplete by definition; `Checkin` enforces completeness on submit.

A draft expires `DRAFT_LIFETIME` after its last edit (`updated_at`). The
rule is applied at read time in app.services.checkin_draft, not by a
scheduled job.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
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

# Same four criteria as Checkin, each nullable here.
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


class CheckinDraft(Base):
    """One user's unfinished check-in."""

    __tablename__ = "checkin_drafts"
    __table_args__ = (
        *(
            CheckConstraint(
                f"{column} BETWEEN {MIN_RATING} AND {MAX_RATING}",
                name=f"ck_checkin_drafts_{column}_range",
            )
            for column in _RATING_COLUMNS
        ),
        CheckConstraint(
            "visibility IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_VISIBILITIES)
            + ")",
            name="ck_checkin_drafts_visibility_allowed",
        ),
        # A visit date without the timezone it was chosen in can't be
        # checked against the visitor's own "today" on submit, so the two
        # are always written together (ADR-0018).
        CheckConstraint(
            "(visited_at IS NULL) = (visited_tz IS NULL)",
            name="ck_checkin_drafts_visited_at_tz_paired",
        ),
        # Serves both the owner's draft list (newest first) and the
        # expiry filter, which are always scoped to one user.
        Index("ix_checkin_drafts_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL rather than CASCADE: losing the venue choice is a smaller
    # loss than losing the whole draft, and the user can pick again.
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venues.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rating_taste: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_service: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_ambiance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # NOT NULL with a default, unlike every other content field: the
    # choice has to survive a device switch, and an absent value would
    # otherwise be filled in silently at submit time (ADR-0018).
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_VISIBILITY
    )
    visited_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    visited_tz: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
