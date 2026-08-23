"""Tests for /api/v1/checkins — the checkin service is mocked."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient, Response
from pytest_mock import MockerFixture

from app.core.auth import get_current_user, get_optional_current_user
from app.core.visibility import Visibility
from app.exceptions import (
    BookmarkNotFoundError,
    CheckinNotFoundError,
    FutureVisitDateError,
    NotCheckinOwnerError,
    VenueNotFoundError,
)
from app.main import app
from app.models.checkin import Checkin
from app.models.user import User

_USER = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")


# All four venue criteria are required (ADR-0011) — shared by the response
# fixture and the create payload so they can't drift apart.
_RATINGS: dict[str, int] = {
    "rating_taste": 4,
    "rating_service": 3,
    "rating_ambiance": 3,
    "rating_value": 2,
}


def _checkin(**overrides: object) -> Checkin:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "user_id": _USER.id,
        "venue_id": uuid4(),
        **_RATINGS,
        "note": None,
        "photo_url": None,
        "visibility": Visibility.PUBLIC,
        "visited_at": date.today(),
        "visited_tz": "Europe/Istanbul",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Checkin(**defaults)


def _create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "venue_id": str(uuid4()),
        "visited_at": date.today().isoformat(),
        "visited_tz": "Europe/Istanbul",
        **_RATINGS,
    }
    payload.update(overrides)
    return payload


async def _post_checkin(client: AsyncClient, **overrides: object) -> Response:
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        return await client.post("/api/v1/checkins", json=_create_payload(**overrides))
    finally:
        app.dependency_overrides.clear()


async def test_create_checkin_returns_201(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.create_checkin",
        AsyncMock(return_value=_checkin()),
    )

    response = await _post_checkin(client)

    assert response.status_code == 201
    body = response.json()
    for field, value in _RATINGS.items():
        assert body[field] == value


async def test_create_checkin_returns_404_when_venue_missing(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.create_checkin",
        AsyncMock(side_effect=VenueNotFoundError("nope")),
    )

    response = await _post_checkin(client)

    assert response.status_code == 404


async def test_create_checkin_returns_422_on_future_visit_date(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.create_checkin",
        AsyncMock(side_effect=FutureVisitDateError("nope")),
    )

    response = await _post_checkin(client)

    assert response.status_code == 422


async def test_get_checkin_returns_200_when_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    checkin = _checkin()
    mocker.patch(
        "app.api.v1.checkins.checkin_service.get_checkin",
        AsyncMock(return_value=checkin),
    )

    response = await client.get(f"/api/v1/checkins/{checkin.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(checkin.id)


async def test_get_checkin_returns_404_when_not_found_or_private(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.get_checkin",
        AsyncMock(side_effect=CheckinNotFoundError("nope")),
    )

    response = await client.get(f"/api/v1/checkins/{uuid4()}")

    assert response.status_code == 404


async def test_update_checkin_returns_200_for_the_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    checkin = _checkin(note="güncellendi")
    mocker.patch(
        "app.api.v1.checkins.checkin_service.update_checkin",
        AsyncMock(return_value=checkin),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/checkins/{checkin.id}", json={"note": "güncellendi"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["note"] == "güncellendi"


async def test_update_checkin_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.update_checkin",
        AsyncMock(side_effect=NotCheckinOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(f"/api/v1/checkins/{uuid4()}", json={"note": "x"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_update_checkin_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.update_checkin",
        AsyncMock(side_effect=CheckinNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(f"/api/v1/checkins/{uuid4()}", json={"note": "x"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_update_checkin_returns_422_on_future_visit_date(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.update_checkin",
        AsyncMock(side_effect=FutureVisitDateError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/checkins/{uuid4()}",
            json={"visited_at": date.today().isoformat()},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_delete_checkin_returns_204_for_the_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.soft_delete_checkin",
        AsyncMock(return_value=None),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/checkins/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_delete_checkin_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.soft_delete_checkin",
        AsyncMock(side_effect=NotCheckinOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/checkins/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_delete_checkin_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.checkin_service.soft_delete_checkin",
        AsyncMock(side_effect=CheckinNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/checkins/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_bookmark_checkin_returns_404_when_checkin_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.bookmark_service.bookmark_checkin",
        AsyncMock(side_effect=CheckinNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/checkins/{uuid4()}/bookmark")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_unbookmark_checkin_returns_404_when_not_bookmarked(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.checkins.bookmark_service.unbookmark_checkin",
        AsyncMock(side_effect=BookmarkNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/checkins/{uuid4()}/bookmark")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_get_checkin_works_without_authentication(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    """The single-checkin GET is public — no dependency override needed."""
    checkin = _checkin(visibility=Visibility.PUBLIC)
    mocker.patch(
        "app.api.v1.checkins.checkin_service.get_checkin",
        AsyncMock(return_value=checkin),
    )
    app.dependency_overrides[get_optional_current_user] = lambda: None

    try:
        response = await client.get(f"/api/v1/checkins/{checkin.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
