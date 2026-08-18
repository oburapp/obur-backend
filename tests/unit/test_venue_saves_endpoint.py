"""Tests for /api/v1/venue-saves — the venue_save service is mocked."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import (
    NotVenueSaveOwnerError,
    VenueNotFoundError,
    VenueSaveNotFoundError,
)
from app.main import app
from app.models.user import User
from app.models.venue_save import VenueSave

_USER = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")


def _save_row(**overrides: object) -> VenueSave:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "user_id": _USER.id,
        "venue_id": uuid4(),
        "type": "visited",
        "visibility": "private",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return VenueSave(**defaults)


async def test_save_venue_returns_201(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.save_venue",
        AsyncMock(return_value=_save_row()),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            "/api/v1/venue-saves", json={"venue_id": str(uuid4()), "type": "visited"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201


async def test_save_venue_returns_404_when_venue_missing(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.save_venue",
        AsyncMock(side_effect=VenueNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            "/api/v1/venue-saves", json={"venue_id": str(uuid4()), "type": "visited"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_get_venue_save_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    row = _save_row()
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.get_venue_save",
        AsyncMock(return_value=row),
    )

    response = await client.get(f"/api/v1/venue-saves/{row.id}")

    assert response.status_code == 200


async def test_get_venue_save_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.get_venue_save",
        AsyncMock(side_effect=VenueSaveNotFoundError("nope")),
    )

    response = await client.get(f"/api/v1/venue-saves/{uuid4()}")

    assert response.status_code == 404


async def test_update_venue_save_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.update_venue_save",
        AsyncMock(return_value=_save_row(visibility="public")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/venue-saves/{uuid4()}", json={"visibility": "public"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["visibility"] == "public"


async def test_update_venue_save_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.update_venue_save",
        AsyncMock(side_effect=VenueSaveNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/venue-saves/{uuid4()}", json={"visibility": "public"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_update_venue_save_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.update_venue_save",
        AsyncMock(side_effect=NotVenueSaveOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/venue-saves/{uuid4()}", json={"visibility": "public"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_delete_venue_save_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.delete_venue_save",
        AsyncMock(return_value=None),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/venue-saves/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_delete_venue_save_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.delete_venue_save",
        AsyncMock(side_effect=VenueSaveNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/venue-saves/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_delete_venue_save_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venue_saves.venue_save_service.delete_venue_save",
        AsyncMock(side_effect=NotVenueSaveOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/venue-saves/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
