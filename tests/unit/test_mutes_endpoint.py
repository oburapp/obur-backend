"""Tests for /api/v1/users/{id}/mute(s), the mute service is mocked."""

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import MuteNotFoundError, SelfMuteError
from app.main import app
from app.models.user import User

_USER = User(
    id=uuid4(),
    auth_provider="clerk",
    auth_provider_id="user_123",
    username="erenm",
    display_name="Eren",
)


async def test_mute_user_returns_422_for_self_mute(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.mutes.mute_service.create_mute",
        AsyncMock(side_effect=SelfMuteError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/users/{_USER.id}/mute")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_mute_user_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.mutes.mute_service.create_mute", AsyncMock(return_value=None)
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/users/{uuid4()}/mute")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_unmute_user_returns_404_when_not_muted(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.mutes.mute_service.remove_mute",
        AsyncMock(side_effect=MuteNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/users/{uuid4()}/mute")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_list_muted_users_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.mutes.mute_service.list_muted_users",
        AsyncMock(return_value=[_USER]),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.get("/api/v1/users/me/mutes")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1
