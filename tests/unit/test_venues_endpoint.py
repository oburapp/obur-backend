"""Tests for /api/v1/venues — the venue service is mocked."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient, Response
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import (
    DuplicateVenueNearbyError,
    VenueCategoryNotFoundError,
    VenueNotFoundError,
)
from app.main import app
from app.models.user import User
from app.models.venue import Venue

_USER = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")


def _venue(**overrides: object) -> Venue:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "name": "Karadeniz Pide",
        "lat": 41.0,
        "lng": 29.0,
        "district": "Kadıköy",
        "address_note": None,
        "google_places_id": None,
        "added_by": _USER.id,
        "category_id": uuid4(),
        "city": "Istanbul",
        "country_code": "TR",
        "timezone": "Europe/Istanbul",
        "is_verified": False,
        "is_active": True,
        "is_suspended": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Venue(**defaults)


async def _post_venue(client: AsyncClient, **overrides: object) -> Response:
    payload: dict[str, object] = {
        "name": "Karadeniz Pide",
        "lat": 41.0,
        "lng": 29.0,
        "category_id": str(uuid4()),
        "district": "Kadıköy",
    }
    payload.update(overrides)
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        return await client.post("/api/v1/venues", json=payload)
    finally:
        app.dependency_overrides.clear()


async def test_create_venue_returns_201_with_valid_payload(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venue = _venue()
    mocker.patch(
        "app.api.v1.venues.venue_service.create_venue",
        AsyncMock(return_value=venue),
    )

    response = await _post_venue(client)

    assert response.status_code == 201
    assert response.json()["name"] == "Karadeniz Pide"


async def test_create_venue_returns_404_when_category_missing(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venues.venue_service.create_venue",
        AsyncMock(side_effect=VenueCategoryNotFoundError("nope")),
    )

    response = await _post_venue(client)

    assert response.status_code == 404


async def test_create_venue_returns_409_with_nearby_venue_id_on_duplicate(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    nearby_id = uuid4()
    mocker.patch(
        "app.api.v1.venues.venue_service.create_venue",
        AsyncMock(side_effect=DuplicateVenueNearbyError(nearby_id)),
    )

    response = await _post_venue(client)

    assert response.status_code == 409
    assert response.json()["nearby_venue_id"] == str(nearby_id)


async def test_list_venues_returns_venues(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venues = [_venue(), _venue()]
    list_mock = mocker.patch(
        "app.api.v1.venues.venue_service.list_venues",
        AsyncMock(return_value=venues),
    )
    search_mock = mocker.patch(
        "app.api.v1.venues.venue_service.search_venues", AsyncMock()
    )

    response = await client.get("/api/v1/venues")

    assert response.status_code == 200
    assert len(response.json()) == 2
    list_mock.assert_awaited_once()
    search_mock.assert_not_awaited()


async def test_list_venues_searches_when_query_param_given(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venues = [_venue(name="Kadıköy'de En İyi Döner")]
    search_mock = mocker.patch(
        "app.api.v1.venues.venue_service.search_venues",
        AsyncMock(return_value=venues),
    )
    list_mock = mocker.patch("app.api.v1.venues.venue_service.list_venues", AsyncMock())

    response = await client.get("/api/v1/venues", params={"q": "döner"})

    assert response.status_code == 200
    assert len(response.json()) == 1
    search_mock.assert_awaited_once()
    list_mock.assert_not_awaited()


async def test_get_venue_returns_venue_when_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venue = _venue()
    mocker.patch(
        "app.api.v1.venues.venue_service.get_venue", AsyncMock(return_value=venue)
    )

    response = await client.get(f"/api/v1/venues/{venue.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(venue.id)


async def test_get_venue_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venues.venue_service.get_venue",
        AsyncMock(side_effect=VenueNotFoundError("nope")),
    )

    response = await client.get(f"/api/v1/venues/{uuid4()}")

    assert response.status_code == 404
