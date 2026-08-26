"""Tests for /api/v1/users/{id}/block(s), the block service is mocked."""

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import BlockNotFoundError, SelfBlockError
from app.main import app
from app.models.user import User

_USER = User(
    id=uuid4(),
    auth_provider="clerk",
    auth_provider_id="user_123",
    username="erenm",
    display_name="Eren",
)


async def test_block_user_returns_422_for_self_block(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.blocks.block_service.create_block",
        AsyncMock(side_effect=SelfBlockError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/users/{_USER.id}/block")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_block_user_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.blocks.block_service.create_block", AsyncMock(return_value=None)
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/users/{uuid4()}/block")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_unblock_user_returns_404_when_not_blocked(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.blocks.block_service.remove_block",
        AsyncMock(side_effect=BlockNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/users/{uuid4()}/block")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_list_blocked_users_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.blocks.block_service.list_blocked_users",
        AsyncMock(return_value=[_USER]),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.get("/api/v1/users/me/blocks")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()) == 1
