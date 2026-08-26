"""CONTENT_REPORT model: an interpersonal-safety report against a
check-in or a user profile (see ADR-0010 in obur-docs, PDD §11).

`target_type`/`target_id` deliberately isn't a real foreign key, the same
choice `NOTIFICATION` already made and for the same reason: a `CHECKIN`
can be permanently purged and a `USER` row is destroyed outright by
account deletion, so a real foreign key would force choosing between
cascading the report away (destroying the audit trail of *why* content
was removed) or blocking the purge itself. Neither is acceptable, so the
application must handle a dangling target gracefully when reading the
admin queue, the same trade-off `NOTIFICATION` already accepted.

`reporter_id`/`resolved_by` both cascade to `NULL` rather than deleting
the row on account deletion: a report is a moderation record, not
personal content, and it survives both the reporter's and the resolving
admin's account deletion with that identity dropped, matching
`VENUE.added_by`'s existing treatment.

`details` is optional free text, except when `reason` is `other`: a
fixed reason vocabulary can't cover everything, so `other` needs the
reporter to actually say what's wrong, or an admin queue entry with no
usable information. Enforced by a correlated `CHECK`, the same pattern
`ck_checkins_visibility_allowed`-style constraints already use elsewhere
in this schema. No length cap at this layer, matching `Checkin.note`
(see app/models/checkin.py): that belongs to the request schema once
Part 3 adds one, not to the column itself.
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


class ContentReportTargetType:
    """Allowed values for `ContentReport.target_type`."""

    CHECKIN = "checkin"
    USER = "user"


_ALLOWED_TARGET_TYPES = (
    ContentReportTargetType.CHECKIN,
    ContentReportTargetType.USER,
)

# PEP 586 only allows literal expressions (not attribute references, even
# to a `Final`-typed class member) as `Literal[...]` arguments, the same
# constraint `app.core.visibility.VisibilityValue` already documents. A
# `test_content_report_target_type_literal_matches_class` unit test keeps
# the two in sync instead.
ContentReportTargetTypeValue = Literal["checkin", "user"]


class ContentReportReason:
    """Allowed values for `ContentReport.reason`, matching the categories
    real platforms (Instagram, Twitter/X, Reddit) converge on, not
    invented from scratch (PDD §11).
    """

    SPAM = "spam"
    HARASSMENT = "harassment"
    HATE_SPEECH = "hate_speech"
    SENSITIVE_CONTENT = "sensitive_content"
    VIOLENCE = "violence"
    FAKE_ACCOUNT = "fake_account"
    OTHER = "other"


_ALLOWED_REASONS = (
    ContentReportReason.SPAM,
    ContentReportReason.HARASSMENT,
    ContentReportReason.HATE_SPEECH,
    ContentReportReason.SENSITIVE_CONTENT,
    ContentReportReason.VIOLENCE,
    ContentReportReason.FAKE_ACCOUNT,
    ContentReportReason.OTHER,
)

# Kept in sync with `ContentReportReason` by
# `test_content_report_reason_literal_matches_class`, the same PEP 586
# constraint `ContentReportTargetTypeValue` above documents.
ContentReportReasonValue = Literal[
    "spam",
    "harassment",
    "hate_speech",
    "sensitive_content",
    "violence",
    "fake_account",
    "other",
]

_ALLOWED_STATUSES = (
    ReportStatus.PENDING,
    ReportStatus.DISMISSED,
    ReportStatus.ACTIONED,
)


class ContentReport(Base):
    """`reporter_id` reporting a check-in or a user profile."""

    __tablename__ = "content_reports"
    __table_args__ = (
        UniqueConstraint(
            "reporter_id",
            "target_type",
            "target_id",
            name="uq_content_reports_reporter_target",
        ),
        CheckConstraint(
            "target_type IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_TARGET_TYPES)
            + ")",
            name="ck_content_reports_target_type_allowed",
        ),
        CheckConstraint(
            "reason IN (" + ", ".join(f"'{value}'" for value in _ALLOWED_REASONS) + ")",
            name="ck_content_reports_reason_allowed",
        ),
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{value}'" for value in _ALLOWED_STATUSES)
            + ")",
            name="ck_content_reports_status_allowed",
        ),
        CheckConstraint(
            f"reason != '{ContentReportReason.OTHER}' "
            "OR (details IS NOT NULL AND details != '')",
            name="ck_content_reports_details_required_for_other",
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
    target_type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
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
