"""End-to-end integration tests for follow endpoints: real DB, real
routing, real exception-to-HTTP mapping.
"""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.main import app
from app.models.user import User


async def _create_user(session: AsyncSession) -> User:
    user = User(auth_provider="clerk", auth_provider_id=f"user_{uuid4()}")
    session.add(user)
    await session.flush()
    return user


async def test_follow_then_appear_in_followers_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: follower

    try:
        follow_response = await client_with_db_session.post(
            f"/api/v1/users/{followee.id}/follow"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert follow_response.status_code == 204

    followers_response = await client_with_db_session.get(
        f"/api/v1/users/{followee.id}/followers"
    )
    assert followers_response.status_code == 200
    assert any(u["id"] == str(follower.id) for u in followers_response.json())
    # email must never appear in a public followers listing.
    assert "email" not in followers_response.json()[0]


async def test_self_follow_returns_422_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        response = await client_with_db_session.post(f"/api/v1/users/{user.id}/follow")
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 422


async def test_unfollow_without_following_returns_404_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: follower

    try:
        response = await client_with_db_session.delete(
            f"/api/v1/users/{followee.id}/follow"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 404


async def test_remove_follower_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: follower

    try:
        await client_with_db_session.post(f"/api/v1/users/{followee.id}/follow")
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = lambda: followee
    try:
        response = await client_with_db_session.delete(
            f"/api/v1/users/me/followers/{follower.id}"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 204


async def test_follow_requires_authentication(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    followee = await _create_user(db_session)

    response = await client_with_db_session.post(f"/api/v1/users/{followee.id}/follow")

    assert response.status_code == 401
