"""Unit tests for the self-service account endpoints — the service layer
is mocked; its own behaviour is covered in test_user_service.py.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import UsernameChangedTooRecentlyError, UsernameTakenError
from app.main import app
from app.models.user import User, UserStatus


def _user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "auth_provider": "clerk",
        "auth_provider_id": "user_123",
        "username": "erenm",
        "display_name": "Eren",
        "email": None,
        "bio": None,
        "avatar_url": None,
        "city": None,
        "country_code": None,
        "locale": "tr",
        "timezone": None,
        "role": "user",
        "status": UserStatus.ACTIVE,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


async def _as(client: AsyncClient, user: User, method: str, url: str, **kwargs: object):
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        return await getattr(client, method)(url, **kwargs)
    finally:
        app.dependency_overrides.clear()


async def test_update_me_returns_the_updated_profile(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    user = _user()
    mocker.patch(
        "app.api.v1.users.user_service.update_profile",
        AsyncMock(return_value=_user(display_name="Eren M")),
    )

    response = await _as(
        client, user, "patch", "/api/v1/users/me", json={"display_name": "Eren M"}
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Eren M"


async def test_update_me_returns_409_when_the_username_is_taken(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.users.user_service.update_profile",
        AsyncMock(side_effect=UsernameTakenError("taken")),
    )

    response = await _as(
        client, _user(), "patch", "/api/v1/users/me", json={"username": "alinmis"}
    )

    assert response.status_code == 409


async def test_update_me_returns_429_when_the_username_changed_too_recently(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.users.user_service.update_profile",
        AsyncMock(side_effect=UsernameChangedTooRecentlyError("too soon")),
    )

    response = await _as(
        client, _user(), "patch", "/api/v1/users/me", json={"username": "yeniad"}
    )

    assert response.status_code == 429


async def test_update_me_rejects_a_username_with_illegal_characters(
    client: AsyncClient,
) -> None:
    """The handle appears in profile URLs and @mentions, so the character
    set is constrained at the schema before any service runs.
    """
    response = await _as(
        client, _user(), "patch", "/api/v1/users/me", json={"username": "eren m!"}
    )

    assert response.status_code == 422


async def test_update_me_never_forwards_role_to_the_service(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    """`role` isn't part of the request schema, so an extra key in the body
    is dropped before the service sees it — a privilege change can't be
    smuggled in alongside a legitimate edit.
    """
    update = mocker.patch(
        "app.api.v1.users.user_service.update_profile",
        AsyncMock(return_value=_user()),
    )

    await _as(
        client,
        _user(),
        "patch",
        "/api/v1/users/me",
        json={"display_name": "Eren M", "role": "admin", "status": "suspended"},
    )

    assert update.await_args is not None
    assert update.await_args.kwargs["changes"] == {"display_name": "Eren M"}


async def test_freeze_me_returns_the_frozen_profile(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.users.user_service.freeze_account",
        AsyncMock(return_value=_user(status=UserStatus.FROZEN)),
    )

    response = await _as(client, _user(), "post", "/api/v1/users/me/freeze")

    assert response.status_code == 200
    assert response.json()["status"] == UserStatus.FROZEN


async def test_delete_me_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    delete = mocker.patch("app.api.v1.users.user_service.delete_account", AsyncMock())
    user = _user()

    response = await _as(client, user, "delete", "/api/v1/users/me")

    assert response.status_code == 204
    delete.assert_awaited_once()
