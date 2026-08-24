"""End-to-end integration tests for the new users.py nested social
routes (lists, venue-saves, bookmarks): real DB, real routing. Also the
N+1 regression test required by docs/testing-strategy.md for
GET /users/me/bookmarks/checkins, which batches each returned check-in's
products the same way GET /venues/{id}/checkins already does.
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
from tests.integration.conftest import QueryCounter

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


async def test_list_user_lists_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        await client_with_db_session.post("/api/v1/lists", json={"title": "Liste"})
    finally:
        del app.dependency_overrides[get_current_user]

    response = await client_with_db_session.get(f"/api/v1/users/{owner.id}/lists")

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_list_user_venue_saves_filters_by_type_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        await client_with_db_session.post(
            "/api/v1/venue-saves",
            json={"venue_id": str(venue.id), "type": "visited", "visibility": "public"},
        )
        await client_with_db_session.post(
            "/api/v1/venue-saves",
            json={
                "venue_id": str(venue.id),
                "type": "wishlist",
                "visibility": "public",
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]

    all_response = await client_with_db_session.get(
        f"/api/v1/users/{owner.id}/venue-saves"
    )
    filtered_response = await client_with_db_session.get(
        f"/api/v1/users/{owner.id}/venue-saves", params={"type": "wishlist"}
    )

    assert len(all_response.json()) == 2
    assert len(filtered_response.json()) == 1
    assert filtered_response.json()[0]["type"] == "wishlist"


async def test_list_my_bookmarked_lists_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        list_id = (
            await client_with_db_session.post("/api/v1/lists", json={"title": "Liste"})
        ).json()["id"]
    finally:
        del app.dependency_overrides[get_current_user]

    app.dependency_overrides[get_current_user] = lambda: bookmarker
    try:
        await client_with_db_session.post(f"/api/v1/lists/{list_id}/bookmark")
        response = await client_with_db_session.get("/api/v1/users/me/bookmarks/lists")
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 200
    assert response.json()[0]["id"] == list_id


async def test_list_my_bookmarked_checkins_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
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
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]
    checkin_id = create_response.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: bookmarker
    try:
        await client_with_db_session.post(f"/api/v1/checkins/{checkin_id}/bookmark")
        response = await client_with_db_session.get(
            "/api/v1/users/me/bookmarks/checkins"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 200
    assert response.json()[0]["id"] == checkin_id
    assert response.json()[0]["rating_taste"] == 4


async def test_listing_my_bookmarked_checkins_does_not_scale_query_count(
    client_with_db_session: AsyncClient,
    db_session: AsyncSession,
    query_counter: QueryCounter,
) -> None:
    """N+1 regression guard (docs/testing-strategy.md): fetching each
    bookmarked check-in's products must stay a fixed number of queries
    regardless of how many are bookmarked.
    """
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)

    async def _create_and_bookmark_checkin() -> None:
        app.dependency_overrides[get_current_user] = lambda: owner
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
            },
        )
        checkin_id = create_response.json()["id"]

        app.dependency_overrides[get_current_user] = lambda: bookmarker
        await client_with_db_session.post(f"/api/v1/checkins/{checkin_id}/bookmark")

    try:
        await _create_and_bookmark_checkin()
        app.dependency_overrides[get_current_user] = lambda: bookmarker
        query_counter.reset()
        small_response = await client_with_db_session.get(
            "/api/v1/users/me/bookmarks/checkins"
        )
        small_count = query_counter.count

        for _ in range(4):
            await _create_and_bookmark_checkin()

        app.dependency_overrides[get_current_user] = lambda: bookmarker
        query_counter.reset()
        large_response = await client_with_db_session.get(
            "/api/v1/users/me/bookmarks/checkins"
        )
        large_count = query_counter.count
    finally:
        del app.dependency_overrides[get_current_user]

    assert len(small_response.json()) == 1
    assert len(large_response.json()) == 5
    assert small_count == large_count
