"""Tests for venue request schema validation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.venue import VenueCreateRequest


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Karadeniz Pide",
        "lat": 41.0,
        "lng": 29.0,
        "category_id": str(uuid4()),
    }
    payload.update(overrides)
    return payload


def test_venue_create_request_accepts_valid_coordinates() -> None:
    request = VenueCreateRequest.model_validate(_payload())

    assert request.confirm_duplicate is False


@pytest.mark.parametrize("lat", [-90.1, 90.1])
def test_venue_create_request_rejects_out_of_range_latitude(lat: float) -> None:
    with pytest.raises(ValidationError):
        VenueCreateRequest.model_validate(_payload(lat=lat))


@pytest.mark.parametrize("lng", [-180.1, 180.1])
def test_venue_create_request_rejects_out_of_range_longitude(lng: float) -> None:
    with pytest.raises(ValidationError):
        VenueCreateRequest.model_validate(_payload(lng=lng))


def test_venue_create_request_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        VenueCreateRequest.model_validate(_payload(name=""))


def test_venue_create_request_rejects_malformed_country_code() -> None:
    with pytest.raises(ValidationError):
        VenueCreateRequest.model_validate(_payload(country_code="TUR"))
