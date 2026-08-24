"""End-to-end integration tests for /api/v1/venues: real DB, real routing,
real exception-to-HTTP mapping — no mocks.
"""

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.main import app
from app.models.user import User
from app.seeds.identity import venue_category_id

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")


async def _create_user(db_session: AsyncSession) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_create_venue_then_fetch_it_by_id(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        create_response = await client_with_db_session.post(
            "/api/v1/venues",
            json={
                "name": "Kadıköy Kahve Durağı",
                "lat": 40.9905,
                "lng": 29.0234,
                "category_id": str(_CAFE_CATEGORY_ID),
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert create_response.status_code == 201
    venue_id = create_response.json()["id"]

    get_response = await client_with_db_session.get(f"/api/v1/venues/{venue_id}")

    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Kadıköy Kahve Durağı"


async def test_create_venue_returns_409_when_duplicate_within_50_meters(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        first = await client_with_db_session.post(
            "/api/v1/venues",
            json={
                "name": "Kadıköy Kahve Durağı",
                "lat": 40.9905,
                "lng": 29.0234,
                "category_id": str(_CAFE_CATEGORY_ID),
            },
        )
        assert first.status_code == 201

        second = await client_with_db_session.post(
            "/api/v1/venues",
            json={
                "name": "Aynı Yerdeki Başka Kafe",
                "lat": 40.99068,
                "lng": 29.0234,
                "category_id": str(_CAFE_CATEGORY_ID),
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert second.status_code == 409
    assert second.json()["detail"]["nearby_venue_id"] == first.json()["id"]


async def test_search_venues_over_http_finds_turkish_name(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        await client_with_db_session.post(
            "/api/v1/venues",
            json={
                "name": "Kadıköy'de En İyi Döner",
                "lat": 40.9905,
                "lng": 29.0234,
                "category_id": str(_CAFE_CATEGORY_ID),
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]

    response = await client_with_db_session.get("/api/v1/venues", params={"q": "döner"})

    assert response.status_code == 200
    assert any(v["name"] == "Kadıköy'de En İyi Döner" for v in response.json())
