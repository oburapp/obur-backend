"""Unit test for app.models.venue_report's `VenueReportReasonValue`
Literal: guards against drift from `VenueReportReason`'s own class
attributes, the same PEP 586 duplication issue as
`Visibility`/`VisibilityValue` (see app.core.visibility and
tests/unit/test_visibility.py).
"""

from typing import get_args

from app.models.venue_report import VenueReportReason, VenueReportReasonValue


def test_venue_report_reason_literal_matches_class_attributes() -> None:
    literal_values = set(get_args(VenueReportReasonValue))
    class_values = {
        VenueReportReason.WRONG_ADDRESS,
        VenueReportReason.WRONG_NAME,
        VenueReportReason.PERMANENTLY_CLOSED,
        VenueReportReason.DUPLICATE,
        VenueReportReason.OTHER,
    }

    assert literal_values == class_values
