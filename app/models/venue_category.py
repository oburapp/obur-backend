"""VENUE_CATEGORY model — hierarchical, language-independent via slug.

Display names live in VenueCategoryTranslation, not here — see the PDD's
"Translation tables over embedded strings" design decision.
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VenueCategory(Base):
    """A hierarchical venue category (e.g. food -> pide)."""

    __tablename__ = "venue_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venue_categories.id"),
        nullable=True,
        index=True,
    )


class VenueCategoryTranslation(Base):
    """Localized display name for a VenueCategory."""

    __tablename__ = "venue_category_translations"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venue_categories.id"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
