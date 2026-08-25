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
from sqlalchemy import (
    CHAR,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.geo import WGS84_SRID
from app.models.base import Base


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
    # The one user reference that isn't purged with the account: a venue
    # is a shared resource other users rely on, not personal content, so
    # it outlives whoever added it and simply loses the attribution.
    # This is why the column is nullable — see ADR-0011 and the PDD's
    # account-deletion decision.
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    # Ilçe / sub-city administrative area. Required for every venue created
    # from Phase 9 onward (enforced in VenueCreateRequest, not here);
    # nullable only because venues created before this phase have no
    # value and there is no backfill (see ADR-0009 in obur-docs).
    district: Mapped[str | None] = mapped_column(String, nullable=True)
    # Cosmetic only, never gates discoverability, ranking, or search.
    # Answers "does this location definitely exist," set automatically
    # once enough independent public check-ins corroborate it (see
    # app/services/venue.py) or, with no google_places_id to anchor it,
    # by an admin. See ADR-0009.
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # The business itself has closed, set only by an admin acting on a
    # report. Unlike is_suspended, the venue stays fully visible, shown
    # transparently rather than hidden (see ADR-0009).
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # A separate admin moderation action, unrelated to whether the
    # business is open. A suspended venue is hidden entirely, its own
    # page reads as nonexistent to anyone but an admin, the same
    # "hidden must be indistinguishable from nonexistent" treatment a
    # blocked profile already gets. Enforced at the RLS layer, not just
    # the application layer (see migrations and ADR-0016).
    is_suspended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
