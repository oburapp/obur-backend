"""Tests for GET /api/v1/users/me."""

from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient

from app.core.auth import get_current_user
from app.main import app
from app.models.user import User


async def test_get_me_returns_the_authenticated_users_profile(
    client: AsyncClient,
) -> None:
    user = User(
        id=uuid4(),
        auth_provider="clerk",
        auth_provider_id="user_123",
        username="erenm",
        email="eren@example.com",
        bio=None,
        avatar_url=None,
        city=None,
        country_code=None,
        locale="tr",
        timezone=None,
        created_at=datetime.now(UTC),
    )
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        response = await client.get("/api/v1/users/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "erenm"
    assert body["email"] == "eren@example.com"
    assert "auth_provider" not in body
    assert "auth_provider_id" not in body
