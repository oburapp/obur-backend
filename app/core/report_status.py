"""Shared moderation-queue status for `CONTENT_REPORT` and `VENUE_REPORT`.

One admin-review workflow, not a bespoke status concept per report kind
(see ADR-0010 in obur-docs): both tables track the same three-state queue,
only what "actioned" means differs per kind.
"""

from typing import Literal


class ReportStatus:
    """Allowed values for a report's `status` column."""

    PENDING = "pending"
    DISMISSED = "dismissed"
    ACTIONED = "actioned"


# PEP 586 only allows literal expressions (not attribute references, even
# to a `Final`-typed class member) as `Literal[...]` arguments, so this
# can't be built from `ReportStatus`'s own attributes, the same
# constraint `app.core.visibility.VisibilityValue` already documents. A
# `test_report_status_literal_matches_class` unit test keeps the two in
# sync instead.
ReportStatusValue = Literal["pending", "dismissed", "actioned"]
