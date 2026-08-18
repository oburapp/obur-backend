"""GLOBAL_PRODUCT_TYPE model — language-independent via slug.

Display names live in GlobalProductTypeTranslation, not here.
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GlobalProductType(Base):
    """A platform-wide product type (e.g. "kuşbaşılı pide"), shared across
    venues so the same dish can be compared and ranked across the platform.
    """

    __tablename__ = "global_product_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venue_categories.id"),
        nullable=False,
        index=True,
    )


class GlobalProductTypeTranslation(Base):
    """Localized display name for a GlobalProductType."""

    __tablename__ = "global_product_type_translations"

    product_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("global_product_types.id"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
