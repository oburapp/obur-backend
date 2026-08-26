"""Tests for /api/v1/admin, the checkin/venue/user/report services are
mocked.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import (
    CheckinNotFoundError,
    ContentReportNotFoundError,
    UserNotFoundError,
    VenueNotEligibleForVerificationError,
    VenueReportNotFoundError,
)
from app.main import app
from app.models.content_report import ContentReport
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.models.venue_report import VenueReport

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


async def test_close_venue_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venue = _venue(is_active=False)
    mocker.patch(
        "app.api.v1.admin.venue_service.close_venue", AsyncMock(return_value=venue)
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/venues/{venue.id}/close")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_close_venue_returns_403_for_a_regular_user(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _REGULAR_USER

    try:
        response = await client.post(f"/api/v1/admin/venues/{uuid4()}/close")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_suspend_venue_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venue = _venue(is_suspended=True)
    mocker.patch(
        "app.api.v1.admin.venue_service.suspend_venue", AsyncMock(return_value=venue)
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/venues/{venue.id}/suspend")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["is_suspended"] is True


async def test_suspend_venue_returns_403_for_a_regular_user(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _REGULAR_USER

    try:
        response = await client.post(f"/api/v1/admin/venues/{uuid4()}/suspend")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_suspend_user_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    target = User(
        id=uuid4(),
        auth_provider="clerk",
        auth_provider_id="user_2",
        username="hedef",
        display_name="Hedef",
        role=UserRole.USER,
        status="suspended",
        locale="tr",
        created_at=datetime.now(UTC),
    )
    mocker.patch(
        "app.api.v1.admin.user_service.suspend_account", AsyncMock(return_value=target)
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/users/{target.id}/suspend")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


async def test_suspend_user_returns_403_for_a_regular_user(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: _REGULAR_USER

    try:
        response = await client.post(f"/api/v1/admin/users/{uuid4()}/suspend")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_suspend_user_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.user_service.suspend_account",
        AsyncMock(side_effect=UserNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/users/{uuid4()}/suspend")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def _content_report(**overrides: object) -> ContentReport:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "reporter_id": uuid4(),
        "target_type": "checkin",
        "target_id": uuid4(),
        "reason": "spam",
        "details": None,
        "status": "pending",
        "resolved_by": None,
        "resolved_at": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return ContentReport(**defaults)


async def test_list_content_reports_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.content_report_service.list_content_reports",
        AsyncMock(return_value=[_content_report()]),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.get("/api/v1/admin/content-reports?status=pending")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_dismiss_content_report_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    report = _content_report(status="dismissed")
    mocker.patch(
        "app.api.v1.admin.content_report_service.dismiss_content_report",
        AsyncMock(return_value=report),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(
            f"/api/v1/admin/content-reports/{report.id}/dismiss"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


async def test_action_content_report_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    report = _content_report(status="actioned")
    mocker.patch(
        "app.api.v1.admin.content_report_service.action_content_report",
        AsyncMock(return_value=report),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(
            f"/api/v1/admin/content-reports/{report.id}/action"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "actioned"


async def test_action_content_report_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.content_report_service.action_content_report",
        AsyncMock(side_effect=ContentReportNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/content-reports/{uuid4()}/action")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def _venue_report(**overrides: object) -> VenueReport:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "reporter_id": uuid4(),
        "venue_id": uuid4(),
        "reason": "wrong_address",
        "details": None,
        "status": "pending",
        "resolved_by": None,
        "resolved_at": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return VenueReport(**defaults)


async def test_list_venue_reports_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.venue_report_service.list_venue_reports",
        AsyncMock(return_value=[_venue_report()]),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.get("/api/v1/admin/venue-reports")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_dismiss_venue_report_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    report = _venue_report(status="dismissed")
    mocker.patch(
        "app.api.v1.admin.venue_report_service.dismiss_venue_report",
        AsyncMock(return_value=report),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/venue-reports/{report.id}/dismiss")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


async def test_action_venue_report_returns_200_for_admin(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    report = _venue_report(status="actioned")
    mocker.patch(
        "app.api.v1.admin.venue_report_service.action_venue_report",
        AsyncMock(return_value=report),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/venue-reports/{report.id}/action")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "actioned"


async def test_action_venue_report_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.admin.venue_report_service.action_venue_report",
        AsyncMock(side_effect=VenueReportNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _ADMIN

    try:
        response = await client.post(f"/api/v1/admin/venue-reports/{uuid4()}/action")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_admin_router_is_excluded_from_the_openapi_schema(
    client: AsyncClient,
) -> None:
    """`include_in_schema=False` (app/api/v1/admin.py's module docstring):
    a web/mobile developer browsing `/docs` must never see these routes.
    """
    response = await client.get("/openapi.json")

    schema = response.json()
    admin_paths = [p for p in schema["paths"] if p.startswith("/api/v1/admin")]
    assert admin_paths == []
