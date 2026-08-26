"""Unit test for app.core.report_status's `ReportStatusValue` Literal:
guards against it drifting from `ReportStatus`'s own class attributes,
the same PEP 586 duplication issue as `Visibility`/`VisibilityValue`
(see app.core.visibility and tests/unit/test_visibility.py).
"""

from typing import get_args

from app.core.report_status import ReportStatus, ReportStatusValue


def test_report_status_literal_matches_class_attributes() -> None:
    literal_values = set(get_args(ReportStatusValue))
    class_values = {
        ReportStatus.PENDING,
        ReportStatus.DISMISSED,
        ReportStatus.ACTIONED,
    }

    assert literal_values == class_values
