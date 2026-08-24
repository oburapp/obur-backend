"""End-to-end integration tests for check-in endpoints: real DB, real
routing, real exception-to-HTTP mapping — no mocks. Also the N+1
regression test required by docs/testing-strategy.md.
"""

from datetime import date
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
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
        name="Kadıköy Kahve Durağı",
        lat=40.9905,
        lng=29.0234,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def test_create_checkin_then_fetch_it_by_id(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    app.dependency_overrides[get_current_user] = lambda: user

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
                "note": "harika",
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert create_response.status_code == 201
    checkin_id = create_response.json()["id"]

    get_response = await client_with_db_session.get(f"/api/v1/checkins/{checkin_id}")
    assert get_response.status_code == 200
    assert get_response.json()["note"] == "harika"
    assert get_response.json()["rating_taste"] == 4


async def test_create_checkin_returns_422_for_future_visit_date(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        response = await client_with_db_session.post(
            "/api/v1/checkins",
            json={
                "venue_id": str(venue.id),
                "rating_taste": 4,
                "rating_service": 3,
                "rating_ambiance": 3,
                "rating_value": 2,
                "visited_at": "2999-01-01",
                "visited_tz": "Europe/Istanbul",
            },
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert response.status_code == 422


async def test_private_checkin_is_hidden_from_other_users_over_http(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
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

    # No auth override active — get_optional_current_user resolves to
    # None, same as an anonymous caller.
    anonymous_response = await client_with_db_session.get(
        f"/api/v1/checkins/{checkin_id}"
    )
    assert anonymous_response.status_code == 404

    app.dependency_overrides[get_optional_current_user] = lambda: other_user
    try:
        other_user_response = await client_with_db_session.get(
            f"/api/v1/checkins/{checkin_id}"
        )
    finally:
        del app.dependency_overrides[get_optional_current_user]
    assert other_user_response.status_code == 404

    app.dependency_overrides[get_optional_current_user] = lambda: owner
    try:
        owner_response = await client_with_db_session.get(
            f"/api/v1/checkins/{checkin_id}"
        )
    finally:
        del app.dependency_overrides[get_optional_current_user]
    assert owner_response.status_code == 200


async def test_owner_can_soft_delete_but_not_hard_delete_via_regular_endpoint(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
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
        checkin_id = create_response.json()["id"]

        delete_response = await client_with_db_session.delete(
            f"/api/v1/checkins/{checkin_id}"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert delete_response.status_code == 204

    get_response = await client_with_db_session.get(f"/api/v1/checkins/{checkin_id}")
    assert get_response.status_code == 404


async def test_regular_user_cannot_purge_a_checkin(
    client_with_db_session: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await _create_user(db_session)
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
        checkin_id = create_response.json()["id"]

        purge_response = await client_with_db_session.delete(
            f"/api/v1/admin/checkins/{checkin_id}"
        )
    finally:
        del app.dependency_overrides[get_current_user]

    assert purge_response.status_code == 403


async def test_listing_venue_checkins_does_not_scale_query_count_with_result_size(
    client_with_db_session: AsyncClient,
    db_session: AsyncSession,
    query_counter: QueryCounter,
) -> None:
    """N+1 regression guard (docs/testing-strategy.md): fetching each
    check-in's products must stay a fixed number of queries regardless
    of how many check-ins the venue has.
    """
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner

    async def _create_checkin() -> None:
        response = await client_with_db_session.post(
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
        assert response.status_code == 201

    try:
        await _create_checkin()

        query_counter.reset()
        small_response = await client_with_db_session.get(
            f"/api/v1/venues/{venue.id}/checkins"
        )
        small_count = query_counter.count

        for _ in range(4):
            await _create_checkin()

        query_counter.reset()
        large_response = await client_with_db_session.get(
            f"/api/v1/venues/{venue.id}/checkins"
        )
        large_count = query_counter.count
    finally:
        del app.dependency_overrides[get_current_user]

    assert len(small_response.json()) == 1
    assert len(large_response.json()) == 5
    assert small_count == large_count
