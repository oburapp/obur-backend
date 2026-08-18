"""CHECKIN_PRODUCT model — one rated product within a check-in.

A check-in can log several products in one visit; each gets its own row
and its own rating. A product can't appear twice in the same check-in
(`uq_checkin_products_checkin_product`) — the PDD's check-in flow rates
each selected product exactly once, and allowing duplicates would only
ever be an accidental double-submit, not a real use case.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ratings import MAX_RATING, MIN_RATING
from app.models.base import Base


class CheckinProduct(Base):
    """A single product's rating within a check-in."""

    __tablename__ = "checkin_products"
    __table_args__ = (
        UniqueConstraint(
            "checkin_id", "product_id", name="uq_checkin_products_checkin_product"
        ),
        CheckConstraint(
            f"rating BETWEEN {MIN_RATING} AND {MAX_RATING}",
            name="ck_checkin_products_rating_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # No separate index on checkin_id — it's already the leading column
    # of uq_checkin_products_checkin_product, which serves lookups by
    # checkin_id alone just as well as a dedicated index would.
    checkin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("checkins.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
