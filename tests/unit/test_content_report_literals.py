"""Unit tests for app.models.content_report's `ContentReportReasonValue`
and `ContentReportTargetTypeValue` Literals: guard against drift from
`ContentReportReason`/`ContentReportTargetType`'s own class attributes,
the same PEP 586 duplication issue as `Visibility`/`VisibilityValue`
(see app.core.visibility and tests/unit/test_visibility.py).
"""

from typing import get_args

from app.models.content_report import (
    ContentReportReason,
    ContentReportReasonValue,
    ContentReportTargetType,
    ContentReportTargetTypeValue,
)


def test_content_report_reason_literal_matches_class_attributes() -> None:
    literal_values = set(get_args(ContentReportReasonValue))
    class_values = {
        ContentReportReason.SPAM,
        ContentReportReason.HARASSMENT,
        ContentReportReason.HATE_SPEECH,
        ContentReportReason.SENSITIVE_CONTENT,
        ContentReportReason.VIOLENCE,
        ContentReportReason.FAKE_ACCOUNT,
        ContentReportReason.OTHER,
    }

    assert literal_values == class_values


def test_content_report_target_type_literal_matches_class_attributes() -> None:
    literal_values = set(get_args(ContentReportTargetTypeValue))
    class_values = {ContentReportTargetType.CHECKIN, ContentReportTargetType.USER}

    assert literal_values == class_values
