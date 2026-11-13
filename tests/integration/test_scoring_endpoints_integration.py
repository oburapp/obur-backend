"""End-to-end tests for the venue score and most-visited places over HTTP
(ADR-0020 in obur-docs).
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.scoring import SCORE_FLOOR
from app.main import app
from app.models.user import User
from tests.integration.conftest import override_current_user
from tests.integration.tagging_factories import create_user, create_venue, post_checkin


@pytest.fixture
async def me(db_session: AsyncSession) -> AsyncGenerator[User, None]:
    user = await create_user(db_session)
    override = override_current_user(user, db_session)
    app.dependency_overrides[get_current_user] = override
    app.dependency_overrides[get_optional_current_user] = override
    yield user
    del app.dependency_overrides[get_current_user]
    del app.dependency_overrides[get_optional_current_user]


async def test_the_venue_page_carries_tiers_and_a_count_never_a_number(
    client_with_db_session: AsyncClient, db_session: AsyncSession, me: User
) -> None:
    venue = await create_venue(db_session, me)
    for _ in range(SCORE_FLOOR):
        await post_checkin(db_session, await create_user(db_session), venue)

    body = (await client_with_db_session.get(f"/api/v1/venues/{venue.id}")).json()

    assert body["score"] == {
        "tier": "somewhat_favorable",
        "criteria": {
            "taste": "extremely_favorable",
            "service": "somewhat_favorable",
            "ambiance": "somewhat_favorable",
            "value": "somewhat_unfavorable",
        },
        "checkin_count": SCORE_FLOOR,
    }


async def test_most_visited_visibility_is_settable_but_never_clearable(
    client_with_db_session: AsyncClient, me: User
) -> None:
    changed = await client_with_db_session.patch(
        "/api/v1/users/me", json={"most_visited_visibility": "public"}
    )
    cleared = await client_with_db_session.patch(
        "/api/v1/users/me", json={"most_visited_visibility": None}
    )

    assert changed.status_code == 200
    assert changed.json()["most_visited_visibility"] == "public"
    assert cleared.status_code == 422


async def test_most_visited_lists_the_owners_venues(
    client_with_db_session: AsyncClient, db_session: AsyncSession, me: User
) -> None:
    venue = await create_venue(db_session, me)
    await post_checkin(db_session, me, venue)

    response = await client_with_db_session.get(f"/api/v1/users/{me.id}/most-visited")

    assert response.json() == [
        {
            "venue_id": str(venue.id),
            "name": venue.name,
            "category_id": str(venue.category_id),
            "visit_count": 1,
        }
    ]
