"""End-to-end integration tests for notification endpoints: real DB,
real routing.
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


async def test_notification_flow_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    followee = await _create_user(db_session)
    follower = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: follower
    try:
        await client_with_db_session.post(f"/api/v1/users/{followee.id}/follow")
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = lambda: followee
    try:
        unread_response = await client_with_db_session.get(
            "/api/v1/users/me/notifications/unread-count"
        )
        list_response = await client_with_db_session.get(
            "/api/v1/users/me/notifications"
        )
        read_all_response = await client_with_db_session.post(
            "/api/v1/users/me/notifications/read-all"
        )
        unread_after_response = await client_with_db_session.get(
            "/api/v1/users/me/notifications/unread-count"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert unread_response.json()["unread_count"] == 1
    assert len(list_response.json()) == 1
    assert list_response.json()[0]["type"] == "new_follower"
    assert read_all_response.status_code == 204
    assert unread_after_response.json()["unread_count"] == 0


async def test_notifications_require_authentication(
    client_with_db_session: AsyncClient,
) -> None:
    response = await client_with_db_session.get("/api/v1/users/me/notifications")

    assert response.status_code == 401
