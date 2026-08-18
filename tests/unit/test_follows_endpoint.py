"""Tests for /api/v1/users/{id}/follow(ers) — the follow service is mocked."""

from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import FollowNotFoundError, SelfFollowError
from app.main import app
from app.models.user import User

_USER = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")


async def test_follow_user_returns_422_for_self_follow(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.follows.follow_service.follow_user",
        AsyncMock(side_effect=SelfFollowError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/users/{_USER.id}/follow")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_unfollow_user_returns_404_when_not_following(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.follows.follow_service.unfollow_user",
        AsyncMock(side_effect=FollowNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/users/{uuid4()}/follow")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_remove_follower_returns_404_when_not_a_follower(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.follows.follow_service.remove_follower",
        AsyncMock(side_effect=FollowNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/users/me/followers/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_list_following_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.follows.follow_service.list_following",
        AsyncMock(return_value=[_USER]),
    )

    response = await client.get(f"/api/v1/users/{uuid4()}/following")

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_list_followers_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.follows.follow_service.list_followers",
        AsyncMock(return_value=[_USER]),
    )

    response = await client.get(f"/api/v1/users/{uuid4()}/followers")

    assert response.status_code == 200
    assert len(response.json()) == 1
