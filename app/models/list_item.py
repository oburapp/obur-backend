"""LIST_ITEM model — one venue's place within a list.

`position` is a fractional-indexing key (see app.services.list), not an
integer sequence — inserting, moving, or removing an item only ever
writes the one row being changed, never renumbers its neighbors. See
ADR-0007 in obur-docs.

`position` is explicitly `COLLATE "C"` (plain byte-wise comparison) —
verified directly against the database that the default `en_US.utf8`
collation sorts base62 keys wrong (e.g. `'Zz' < 'a0'` is *false* under
`en_US.utf8`, but the fractional-indexing algorithm requires it to be
*true*, since it relies on ordinary ASCII byte ordering). Without this,
`ORDER BY position` silently returns items in the wrong order.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ListItem(Base):
    """A venue's membership and position within a list."""

    __tablename__ = "list_items"
    __table_args__ = (
        UniqueConstraint("list_id", "venue_id", name="uq_list_items_list_venue"),
        Index("ix_list_items_list_id_position", "list_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lists.id", ondelete="CASCADE"), nullable=False
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    position: Mapped[str] = mapped_column(String(collation="C"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
