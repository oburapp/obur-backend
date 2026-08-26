"""Tests for report request schema validation."""

import pytest
from pydantic import ValidationError

from app.schemas.report import ContentReportCreateRequest, VenueReportCreateRequest


def test_content_report_create_request_accepts_a_fixed_reason() -> None:
    request = ContentReportCreateRequest.model_validate({"reason": "spam"})

    assert request.details is None


def test_content_report_create_request_rejects_other_without_details() -> None:
    with pytest.raises(ValidationError):
        ContentReportCreateRequest.model_validate({"reason": "other"})


def test_content_report_create_request_rejects_other_with_blank_details() -> None:
    with pytest.raises(ValidationError):
        ContentReportCreateRequest.model_validate({"reason": "other", "details": "   "})


def test_content_report_create_request_accepts_other_with_details() -> None:
    request = ContentReportCreateRequest.model_validate(
        {"reason": "other", "details": "Sahte hesap gibi görünüyor."}
    )

    assert request.details == "Sahte hesap gibi görünüyor."


def test_content_report_create_request_rejects_an_unknown_reason() -> None:
    with pytest.raises(ValidationError):
        ContentReportCreateRequest.model_validate({"reason": "not_a_real_reason"})


def test_venue_report_create_request_accepts_a_fixed_reason() -> None:
    request = VenueReportCreateRequest.model_validate({"reason": "wrong_address"})

    assert request.details is None


def test_venue_report_create_request_rejects_other_without_details() -> None:
    with pytest.raises(ValidationError):
        VenueReportCreateRequest.model_validate({"reason": "other"})


def test_venue_report_create_request_accepts_other_with_details() -> None:
    request = VenueReportCreateRequest.model_validate(
        {"reason": "other", "details": "Bu mekan artık başka bir şey."}
    )

    assert request.details == "Bu mekan artık başka bir şey."
