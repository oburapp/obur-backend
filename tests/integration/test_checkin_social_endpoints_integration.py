"""End-to-end integration tests for check-in like/bookmark endpoints:
real DB, real routing, real exception-to-HTTP mapping.
"""

from datetime import date
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.main import app
from app.models.product import Product
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import global_product_type_id, venue_category_id

_CAFE_CATEGORY_ID = venue_category_id("cafe")
_FILTER_COFFEE_TYPE_ID = global_product_type_id("filter-coffee")


async def _create_user(session: AsyncSession) -> User:
    user = User(auth_provider="clerk", auth_provider_id=f"user_{uuid4()}")
    session.add(user)
    await session.flush()
    return user


async def _create_venue_with_product(
    session: AsyncSession, owner: User
) -> tuple[Venue, str]:
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
    )
    session.add(venue)
    await session.flush()
    product = Product(
        venue_id=venue.id,
        global_type_id=_FILTER_COFFEE_TYPE_ID,
        name="Filtre",
        is_available=True,
    )
    session.add(product)
    await session.flush()
    return venue, str(product.id)


async def _create_checkin_id(client: AsyncClient, venue: Venue, product_id: str) -> str:
    response = await client.post(
        "/api/v1/checkins",
        json={
            "venue_id": str(venue.id),
            "products": [{"product_id": product_id, "rating": 4}],
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
    venue, product_id = await _create_venue_with_product(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        checkin_id = await _create_checkin_id(client_with_db_session, venue, product_id)
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
    venue, product_id = await _create_venue_with_product(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        create_response = await client_with_db_session.post(
            "/api/v1/checkins",
            json={
                "venue_id": str(venue.id),
                "products": [{"product_id": product_id, "rating": 4}],
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
    venue, product_id = await _create_venue_with_product(db_session, owner)
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        checkin_id = await _create_checkin_id(client_with_db_session, venue, product_id)
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
