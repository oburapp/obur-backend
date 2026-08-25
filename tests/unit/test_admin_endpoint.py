"""Tests for /api/v1/admin — the checkin and venue services are mocked."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import CheckinNotFoundError, VenueNotEligibleForVerificationError
from app.main import app
from app.models.user import User, UserRole
from app.models.venue import Venue

_ADMIN = User(
    id=uuid4(), auth_provider="clerk", auth_provider_id="admin_1", role=UserRole.ADMIN
)
_REGULAR_USER = User(
    id=uuid4(), auth_provider="clerk", auth_provider_id="user_1", role=UserRole.USER
)


async def test_purge_checkin_returns_204_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.checkin_service.hard_delete_checkin",
        AsyncMock(return_value=None),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.delete(f"/api/v1/admin/checkins/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_purge_checkin_returns_403_for_a_regular_user(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _REGULAR_USER

    try:
        response = await client.delete(f"/api/v1/admin/checkins/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_purge_checkin_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.checkin_service.hard_delete_checkin",
        AsyncMock(side_effect=CheckinNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.delete(f"/api/v1/admin/checkins/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def _venue(**overrides: object) -> Venue:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "name": "Karadeniz Pide",
        "lat": 41.0,
        "lng": 29.0,
        "district": "Kadıköy",
        "address_note": None,
        "google_places_id": None,
        "added_by": uuid4(),
        "category_id": uuid4(),
        "city": "Istanbul",
        "country_code": "TR",
        "timezone": "Europe/Istanbul",
        "is_verified": True,
        "is_active": True,
        "is_suspended": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Venue(**defaults)


async def test_verify_venue_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venue = _venue()
    mocker.patch(
        "app.api.v1.admin.venue_service.verify_venue_by_admin",
        AsyncMock(return_value=venue),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/venues/{venue.id}/verify")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["is_verified"] is True


async def test_verify_venue_returns_403_for_a_regular_user(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _REGULAR_USER

    try:
        response = await client.post(f"/api/v1/admin/venues/{uuid4()}/verify")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_verify_venue_returns_409_when_below_checkin_threshold(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.venue_service.verify_venue_by_admin",
        AsyncMock(side_effect=VenueNotEligibleForVerificationError("not enough")),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/venues/{uuid4()}/verify")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
