"""Tests for /api/v1/admin — the checkin service is mocked."""

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import CheckinNotFoundError
from app.main import app
from app.models.user import User, UserRole

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
