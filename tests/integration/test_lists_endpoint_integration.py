"""End-to-end integration tests for list endpoints (CRUD, items, like,
bookmark): real DB, real routing, real exception-to-HTTP mapping.
"""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.database import set_current_user_identity
from app.main import app
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from tests.integration.conftest import override_current_user

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")


async def _create_user(session: AsyncSession) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    session.add(user)
    await session.flush()
    return user


async def _create_venue(session: AsyncSession, added_by: User) -> Venue:
    # Venue creation now requires an authenticated identity (RLS,
    # migration c1d5a8f042e7).
    await set_current_user_identity(session, added_by.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def test_create_list_then_fetch_it_by_id(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = override_current_user(
        owner, db_session
    )

    try:
        create_response = await client_with_db_session.post(
            "/api/v1/lists", json={"title": "Kadıköy Kahveleri"}
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert create_response.status_code == 201
    list_id = create_response.json()["id"]

    get_response = await client_with_db_session.get(f"/api/v1/lists/{list_id}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Kadıköy Kahveleri"
    assert get_response.json()["visibility"] == "public"


async def test_private_list_is_hidden_from_other_users_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = override_current_user(
        owner, db_session
    )

    try:
        create_response = await client_with_db_session.post(
            "/api/v1/lists", json={"title": "Özel", "visibility": "private"}
        )
    finally:
        del app.dependency_overrides[get_current_user]
    list_id = create_response.json()["id"]

    app.dependency_overrides[get_optional_current_user] = override_current_user(
        other_user, db_session
    )
    try:
        response = await client_with_db_session.get(f"/api/v1/lists/{list_id}")
    finally:
        del app.dependency_overrides[get_optional_current_user]

    assert response.status_code == 404


async def test_add_item_then_move_it_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    venue_a = await _create_venue(db_session, owner)
    venue_b = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = override_current_user(
        owner, db_session
    )

    try:
        list_id = (
            await client_with_db_session.post("/api/v1/lists", json={"title": "Liste"})
        ).json()["id"]
        item_a = await client_with_db_session.post(
            f"/api/v1/lists/{list_id}/items", json={"venue_id": str(venue_a.id)}
        )
        item_b = await client_with_db_session.post(
            f"/api/v1/lists/{list_id}/items", json={"venue_id": str(venue_b.id)}
        )
        move_response = await client_with_db_session.patch(
            f"/api/v1/lists/{list_id}/items/{item_b.json()['id']}/move",
            json={"after_item_id": None},
        )
        items_response = await client_with_db_session.get(
            f"/api/v1/lists/{list_id}/items"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert item_a.status_code == 201
    assert move_response.status_code == 200
    ordered_ids = [item["id"] for item in items_response.json()]
    assert ordered_ids == [item_b.json()["id"], item_a.json()["id"]]


async def test_add_duplicate_venue_returns_409_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = override_current_user(
        owner, db_session
    )

    try:
        list_id = (
            await client_with_db_session.post("/api/v1/lists", json={"title": "Liste"})
        ).json()["id"]
        await client_with_db_session.post(
            f"/api/v1/lists/{list_id}/items", json={"venue_id": str(venue.id)}
        )
        duplicate_response = await client_with_db_session.post(
            f"/api/v1/lists/{list_id}/items", json={"venue_id": str(venue.id)}
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert duplicate_response.status_code == 409


async def test_like_then_unlike_a_list_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    liker = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = override_current_user(
        owner, db_session
    )
    try:
        list_id = (
            await client_with_db_session.post("/api/v1/lists", json={"title": "Liste"})
        ).json()["id"]
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = override_current_user(
        liker, db_session
    )
    try:
        like_response = await client_with_db_session.post(
            f"/api/v1/lists/{list_id}/like"
        )
        unlike_response = await client_with_db_session.delete(
            f"/api/v1/lists/{list_id}/like"
        )
        unlike_again_response = await client_with_db_session.delete(
            f"/api/v1/lists/{list_id}/like"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert like_response.status_code == 204
    assert unlike_response.status_code == 204
    assert unlike_again_response.status_code == 404


async def test_bookmark_a_list_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = override_current_user(
        owner, db_session
    )
    try:
        list_id = (
            await client_with_db_session.post("/api/v1/lists", json={"title": "Liste"})
        ).json()["id"]
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = override_current_user(
        bookmarker, db_session
    )
    try:
        response = await client_with_db_session.post(
            f"/api/v1/lists/{list_id}/bookmark"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 204


async def test_delete_list_by_non_owner_returns_403_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = override_current_user(
        owner, db_session
    )
    try:
        list_id = (
            await client_with_db_session.post("/api/v1/lists", json={"title": "Liste"})
        ).json()["id"]
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = override_current_user(
        stranger, db_session
    )
    try:
        response = await client_with_db_session.delete(f"/api/v1/lists/{list_id}")
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 403
