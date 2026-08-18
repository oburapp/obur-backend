"""Tests for /api/v1/lists — the list/like/bookmark services are mocked."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import (
    BookmarkNotFoundError,
    DuplicateListItemError,
    LikeNotFoundError,
    ListItemNotFoundError,
    ListNotFoundError,
    NotListOwnerError,
)
from app.main import app
from app.models.list import List
from app.models.list_item import ListItem
from app.models.user import User

_USER = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")


def _list_row(**overrides: object) -> List:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "user_id": _USER.id,
        "title": "Liste",
        "description": None,
        "visibility": "public",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return List(**defaults)


def _list_item_row(**overrides: object) -> ListItem:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "list_id": uuid4(),
        "venue_id": uuid4(),
        "position": "a0",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return ListItem(**defaults)


async def test_create_list_returns_201(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.create_list",
        AsyncMock(return_value=_list_row()),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post("/api/v1/lists", json={"title": "Liste"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["title"] == "Liste"


async def test_get_list_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.get_list",
        AsyncMock(side_effect=ListNotFoundError("nope")),
    )

    response = await client.get(f"/api/v1/lists/{uuid4()}")

    assert response.status_code == 404


async def test_update_list_returns_200_for_the_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    row = _list_row(title="güncellendi")
    mocker.patch(
        "app.api.v1.lists.list_service.update_list", AsyncMock(return_value=row)
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/lists/{row.id}", json={"title": "güncellendi"}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["title"] == "güncellendi"


async def test_update_list_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.update_list",
        AsyncMock(side_effect=ListNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(f"/api/v1/lists/{uuid4()}", json={"title": "x"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_update_list_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.update_list",
        AsyncMock(side_effect=NotListOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(f"/api/v1/lists/{uuid4()}", json={"title": "x"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_delete_list_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.delete_list",
        AsyncMock(side_effect=ListNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/lists/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_delete_list_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.delete_list",
        AsyncMock(side_effect=NotListOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/lists/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_list_items_returns_404_when_list_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.get_list",
        AsyncMock(side_effect=ListNotFoundError("nope")),
    )

    response = await client.get(f"/api/v1/lists/{uuid4()}/items")

    assert response.status_code == 404


async def test_list_items_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.get_list", AsyncMock(return_value=_list_row())
    )
    mocker.patch(
        "app.api.v1.lists.list_service.list_items_for_list",
        AsyncMock(return_value=[_list_item_row()]),
    )

    response = await client.get(f"/api/v1/lists/{uuid4()}/items")

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_add_list_item_returns_201(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.add_list_item",
        AsyncMock(return_value=_list_item_row()),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/lists/{uuid4()}/items", json={"venue_id": str(uuid4())}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201


async def test_add_list_item_returns_404_when_list_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.add_list_item",
        AsyncMock(side_effect=ListNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/lists/{uuid4()}/items", json={"venue_id": str(uuid4())}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_add_list_item_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.add_list_item",
        AsyncMock(side_effect=NotListOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/lists/{uuid4()}/items", json={"venue_id": str(uuid4())}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_add_list_item_returns_422_on_duplicate(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.add_list_item",
        AsyncMock(side_effect=DuplicateListItemError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(
            f"/api/v1/lists/{uuid4()}/items", json={"venue_id": str(uuid4())}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_move_list_item_returns_200(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.move_list_item",
        AsyncMock(return_value=_list_item_row()),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/lists/{uuid4()}/items/{uuid4()}/move",
            json={"after_item_id": None},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


async def test_move_list_item_returns_404_when_item_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.move_list_item",
        AsyncMock(side_effect=ListItemNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/lists/{uuid4()}/items/{uuid4()}/move",
            json={"after_item_id": None},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_move_list_item_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.move_list_item",
        AsyncMock(side_effect=NotListOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.patch(
            f"/api/v1/lists/{uuid4()}/items/{uuid4()}/move",
            json={"after_item_id": None},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_remove_list_item_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.remove_list_item", AsyncMock(return_value=None)
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/lists/{uuid4()}/items/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204


async def test_remove_list_item_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.remove_list_item",
        AsyncMock(side_effect=ListItemNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/lists/{uuid4()}/items/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_remove_list_item_returns_403_when_not_owner(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.list_service.remove_list_item",
        AsyncMock(side_effect=NotListOwnerError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/lists/{uuid4()}/items/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


async def test_like_list_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.like_service.like_list",
        AsyncMock(side_effect=ListNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/lists/{uuid4()}/like")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_unlike_list_returns_404_when_not_liked(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.like_service.unlike_list",
        AsyncMock(side_effect=LikeNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/lists/{uuid4()}/like")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_bookmark_list_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.bookmark_service.bookmark_list",
        AsyncMock(side_effect=ListNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.post(f"/api/v1/lists/{uuid4()}/bookmark")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


async def test_unbookmark_list_returns_404_when_not_bookmarked(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.lists.bookmark_service.unbookmark_list",
        AsyncMock(side_effect=BookmarkNotFoundError("nope")),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER

    try:
        response = await client.delete(f"/api/v1/lists/{uuid4()}/bookmark")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
