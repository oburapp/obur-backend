"""Tests for /api/v1/{checkins,users,venues}/{id}/report, the report
services are mocked.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import CheckinNotFoundError, VenueNotFoundError
from app.main import app
from app.models.user import User

_USER = User(
    id=uuid4(),
    auth_provider="clerk",
    auth_provider_id="user_123",
    username="erenm",
    display_name="Eren",
)


async def test_report_checkin_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.reports.content_report_service.create_content_report",
        AsyncMock(return_value=None),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/checkins/{uuid4()}/report", json={"reason": "spam"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_report_checkin_returns_404_when_not_visible(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.reports.content_report_service.create_content_report",
        AsyncMock(side_effect=CheckinNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/checkins/{uuid4()}/report", json={"reason": "spam"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_report_checkin_returns_422_for_other_without_details(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/checkins/{uuid4()}/report", json={"reason": "other"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_report_user_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.reports.content_report_service.create_content_report",
        AsyncMock(return_value=None),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/users/{uuid4()}/report", json={"reason": "harassment"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_report_venue_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.reports.venue_report_service.create_venue_report",
        AsyncMock(return_value=None),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/venues/{uuid4()}/report", json={"reason": "duplicate"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_report_venue_returns_404_when_venue_missing(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.reports.venue_report_service.create_venue_report",
        AsyncMock(side_effect=VenueNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/venues/{uuid4()}/report", json={"reason": "duplicate"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
