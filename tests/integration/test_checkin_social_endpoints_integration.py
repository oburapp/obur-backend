"""End-to-end integration tests for check-in like/bookmark endpoints:
real DB, real routing, real exception-to-HTTP mapping.
"""

from datetime import date
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
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


async def _create_venue(session: AsyncSession, owner: User) -> Venue:
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def _create_checkin_id(client: AsyncClient, venue: Venue) -> str:
    response = await client.post(
        "/api/v1/checkins",
        json={
            "venue_id": str(venue.id),
            "rating_taste": 4,
            "rating_service": 3,
            "rating_ambiance": 3,
            "rating_value": 2,
            "visited_at": date.today().isoformat(),
            "visited_tz": "Europe/Istanbul",
        },
    )
    return response.json()["id"]


async def test_like_then_unlike_a_checkin_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    liker = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        checkin_id = await _create_checkin_id(client_with_db_session, venue)
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = lambda: liker
    try:
        like_response = await client_with_db_session.post(
            f"/api/v1/checkins/{checkin_id}/like"
        )
        unlike_response = await client_with_db_session.delete(
            f"/api/v1/checkins/{checkin_id}/like"
        )
        unlike_again_response = await client_with_db_session.delete(
            f"/api/v1/checkins/{checkin_id}/like"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert like_response.status_code == 204
    assert unlike_response.status_code == 204
    assert unlike_again_response.status_code == 404


async def test_liking_a_private_checkin_returns_404_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        create_response = await client_with_db_session.post(
            "/api/v1/checkins",
            json={
                "venue_id": str(venue.id),
                "rating_taste": 4,
                "rating_service": 3,
                "rating_ambiance": 3,
                "rating_value": 2,
                "visited_at": date.today().isoformat(),
                "visited_tz": "Europe/Istanbul",
                "visibility": "private",
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]
    checkin_id = create_response.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: stranger
    try:
        response = await client_with_db_session.post(
            f"/api/v1/checkins/{checkin_id}/like"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 404


async def test_bookmark_then_unbookmark_a_checkin_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        checkin_id = await _create_checkin_id(client_with_db_session, venue)
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = lambda: bookmarker
    try:
        bookmark_response = await client_with_db_session.post(
            f"/api/v1/checkins/{checkin_id}/bookmark"
        )
        unbookmark_response = await client_with_db_session.delete(
            f"/api/v1/checkins/{checkin_id}/bookmark"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert bookmark_response.status_code == 204
    assert unbookmark_response.status_code == 204
