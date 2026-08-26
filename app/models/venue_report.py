"""VENUE_REPORT model: a data-quality report against a venue's details
(see ADR-0010 in obur-docs, PDD §11). The only way a venue's details ever
change after creation, since no venue field is user-editable, not even
by whoever added it (ADR-0009).

`venue_id` is a real foreign key, unlike `ContentReport.target_id`: a
`VENUE` row is never deleted, closed sets `is_active = false` and
suspended sets `is_suspended = true`, so the target's existence is
guaranteed and the foreign key costs nothing.

`reporter_id`/`resolved_by` both cascade to `NULL` on account deletion,
the same treatment `ContentReport` gives them and for the same reason: a
report is a moderation record, not personal content.

`details` is optional free text, required only when `reason` is
`other`, the same correlated `CHECK` `ContentReport.details` uses and
for the same reason: `other` needs the reporter to actually say what's
wrong.
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.report_status import ReportStatus
from app.models.base import Base

_DEFAULT_STATUS = ReportStatus.PENDING


class VenueReportReason:
    """Allowed values for `VenueReport.reason` (PDD §11)."""

    WRONG_ADDRESS = "wrong_address"
    WRONG_NAME = "wrong_name"
    PERMANENTLY_CLOSED = "permanently_closed"
    DUPLICATE = "duplicate"
    OTHER = "other"


_ALLOWED_REASONS = (
    VenueReportReason.WRONG_ADDRESS,
    VenueReportReason.WRONG_NAME,
    VenueReportReason.PERMANENTLY_CLOSED,
    VenueReportReason.DUPLICATE,
    VenueReportReason.OTHER,
)

# Kept in sync with `VenueReportReason` by
# `test_venue_report_reason_literal_matches_class`, the same PEP 586
# constraint `app.core.visibility.VisibilityValue` already documents.
VenueReportReasonValue = Literal[
    "wrong_address", "wrong_name", "permanently_closed", "duplicate", "other"
]

_ALLOWED_STATUSES = (
    ReportStatus.PENDING,
    ReportStatus.DISMISSED,
    ReportStatus.ACTIONED,
)


class VenueReport(Base):
    """`reporter_id` reporting a data-quality issue on `venue_id`."""

    __tablename__ = "venue_reports"
    __table_args__ = (
        UniqueConstraint(
            "reporter_id", "venue_id", name="uq_venue_reports_reporter_venue"
        ),
        CheckConstraint(
            "reason IN (" + ", ".join(f"'{value}'" for value in _ALLOWED_REASONS) + ")",
            name="ck_venue_reports_reason_allowed",
        ),
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_STATUSES)
            + ")",
            name="ck_venue_reports_status_allowed",
        ),
        CheckConstraint(
            f"reason != '{VenueReportReason.OTHER}' "
            "OR (details IS NOT NULL AND details != '')",
            name="ck_venue_reports_details_required_for_other",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=_DEFAULT_STATUS
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
