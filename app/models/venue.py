"""VENUE model.

Identity is coordinate-based, not name-based — see the PDD's
"Coordinate-based venue identity" design decision. `location` is a
generated column derived from `lat`/`lng`, so it can never drift out of
sync with them — no application code writes to it.

Name search is backed by a `pg_trgm` GIN index on
`immutable_unaccent(name)`, created directly in migration
`ed402e8663f4` — see ADR-0003 in obur-docs. It isn't declared here via
SQLAlchemy's `Index()` construct: expression indexes with a
PostgreSQL-specific operator class don't map cleanly onto the ORM's
index API, and Alembic autogenerate can't reliably reflect this kind of
index either way — this is the same category of limitation already
documented for `idx_venues_location` (see migrations/env.py).
"""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import CHAR, Computed, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.geo import WGS84_SRID
from app.models.base import Base

# Default status for a newly added venue.
_DEFAULT_VENUE_STATUS = "active"


class Venue(Base):
    """A place — restaurant, cafe, bar, etc."""

    __tablename__ = "venues"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    # Generated from lat/lng — never set directly, only queried against
    # (e.g. ST_DWithin for duplicate detection). See app/services/venue.py.
    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=WGS84_SRID),
        Computed(
            f"ST_SetSRID(ST_MakePoint(lng, lat), {WGS84_SRID})::geography",
            persisted=True,
        ),
    )
    address_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_places_id: Mapped[str | None] = mapped_column(String, nullable=True)
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venue_categories.id"),
        nullable=False,
        index=True,
    )
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_VENUE_STATUS
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
