"""End-to-end integration tests for close-friend endpoints: real DB,
real routing, real exception-to-HTTP mapping.
"""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.main import app
from app.models.user import User


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


async def test_add_close_friend_requires_a_current_follower_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    non_follower = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: owner

    try:
        response = await client_with_db_session.post(
            f"/api/v1/users/me/close-friends/{non_follower.id}"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 422


async def test_add_then_list_close_friends_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    follower = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: follower
    try:
        await client_with_db_session.post(f"/api/v1/users/{owner.id}/follow")
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        add_response = await client_with_db_session.post(
            f"/api/v1/users/me/close-friends/{follower.id}"
        )
        list_response = await client_with_db_session.get(
            "/api/v1/users/me/close-friends"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert add_response.status_code == 204
    assert list_response.status_code == 200
    assert any(u["id"] == str(follower.id) for u in list_response.json())


async def test_remove_close_friend_not_on_the_list_returns_404_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: owner

    try:
        response = await client_with_db_session.delete(
            f"/api/v1/users/me/close-friends/{stranger.id}"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 404
