"""End-to-end integration tests for venue-save endpoints: real DB, real
routing, real exception-to-HTTP mapping.
"""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.main import app
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id

_CAFE_CATEGORY_ID = venue_category_id("cafe")


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


async def test_save_venue_defaults_to_private_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        response = await client_with_db_session.post(
            "/api/v1/venue-saves", json={"venue_id": str(venue.id), "type": "visited"}
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 201
    assert response.json()["visibility"] == "private"


async def test_invalid_type_returns_422_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        response = await client_with_db_session.post(
            "/api/v1/venue-saves",
            json={"venue_id": str(venue.id), "type": "not_a_real_type"},
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 422


async def test_private_venue_save_is_hidden_from_other_users_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner

    try:
        create_response = await client_with_db_session.post(
            "/api/v1/venue-saves", json={"venue_id": str(venue.id), "type": "wishlist"}
        )
    finally:
        del app.dependency_overrides[get_current_user]
    save_id = create_response.json()["id"]

    app.dependency_overrides[get_optional_current_user] = lambda: other_user
    try:
        response = await client_with_db_session.get(f"/api/v1/venue-saves/{save_id}")
    finally:
        del app.dependency_overrides[get_optional_current_user]

    assert response.status_code == 404


async def test_update_visibility_then_delete_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner

    try:
        save_id = (
            await client_with_db_session.post(
                "/api/v1/venue-saves",
                json={"venue_id": str(venue.id), "type": "favorite"},
            )
        ).json()["id"]

        update_response = await client_with_db_session.patch(
            f"/api/v1/venue-saves/{save_id}", json={"visibility": "public"}
        )
        delete_response = await client_with_db_session.delete(
            f"/api/v1/venue-saves/{save_id}"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert update_response.status_code == 200
    assert update_response.json()["visibility"] == "public"
    assert delete_response.status_code == 204
