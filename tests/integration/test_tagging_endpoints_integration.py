"""End-to-end tests for mentions and hashtags over HTTP (ADR-0019 in
obur-docs): the response shape, the problem types, the mentionable and
hashtag endpoints, and the N+1 guard docs/testing-strategy.md requires for
a new list endpoint.
"""

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.idempotency import IDEMPOTENCY_KEY_HEADER
from app.core.text_tokens import mention_token
from app.main import app
from app.models.user import User
from app.models.venue import Venue
from tests.integration.conftest import QueryCounter, override_current_user
from tests.integration.tagging_factories import (
    befriend,
    create_user,
    create_venue,
    mentioning,
    post_checkin,
)

_PROBLEM = "urn:obur:problem:"
_PAGE_GROWTH = 4


@pytest.fixture
async def author(db_session: AsyncSession) -> AsyncGenerator[User, None]:
    user = await create_user(db_session, username="yazar")
    app.dependency_overrides[get_current_user] = override_current_user(user, db_session)
    yield user
    del app.dependency_overrides[get_current_user]


@pytest.fixture
async def venue(db_session: AsyncSession, author: User) -> Venue:
    return await create_venue(db_session, author)


async def _submit(client: AsyncClient, venue: Venue, note: str) -> Any:
    return await client.post(
        "/api/v1/checkins",
        headers={IDEMPOTENCY_KEY_HEADER: str(uuid4())},
        json={
            "venue_id": str(venue.id),
            "rating_taste": 4,
            "rating_service": 3,
            "rating_ambiance": 3,
            "rating_value": 2,
            "visited_at": date.today().isoformat(),
            "visited_tz": "Europe/Istanbul",
            "note": note,
        },
    )


async def test_a_checkin_response_resolves_mentions_to_usernames(
    client_with_db_session: AsyncClient,
    db_session: AsyncSession,
    author: User,
    venue: Venue,
) -> None:
    ali = await create_user(db_session, username="ali")
    await befriend(db_session, author, ali)

    created = await _submit(client_with_db_session, venue, mentioning(ali))
    fetched = await client_with_db_session.get(
        f"/api/v1/checkins/{created.json()['id']}"
    )

    assert created.status_code == 201
    assert fetched.json()["mentions"] == [{"user_id": str(ali.id), "username": "ali"}]
    assert fetched.json()["note"] == f"lunch with {mention_token(ali.id)}"


@pytest.mark.parametrize(
    ("note", "problem"),
    [
        (f"hi {mention_token(uuid4())}", "mention-not-allowed"),
        ("#a1 #b2 #c3 #d4 #e5 #f6", "too-many-hashtags"),
        ("#" + "a" * 51, "hashtag-too-long"),
    ],
)
async def test_invalid_tagging_is_a_422_problem(
    client_with_db_session: AsyncClient,
    author: User,
    venue: Venue,
    note: str,
    problem: str,
) -> None:
    response = await _submit(client_with_db_session, venue, note)

    assert response.status_code == 422
    assert response.json()["type"] == f"{_PROBLEM}{problem}"


async def test_the_mentionable_endpoint_lists_eligible_people(
    client_with_db_session: AsyncClient, db_session: AsyncSession, author: User
) -> None:
    ali = await create_user(db_session, username="ali_k")
    await befriend(db_session, author, ali)

    public = await client_with_db_session.get(
        "/api/v1/users/me/mentionable", params={"visibility": "public", "q": "ali"}
    )
    private = await client_with_db_session.get(
        "/api/v1/users/me/mentionable", params={"visibility": "private"}
    )

    assert [user["id"] for user in public.json()] == [str(ali.id)]
    assert private.json() == []


async def test_hashtag_pages_match_any_casing(
    client_with_db_session: AsyncClient, author: User, venue: Venue
) -> None:
    created = await _submit(client_with_db_session, venue, "#Kahve keyfi")

    checkins = await client_with_db_session.get("/api/v1/hashtags/KAHVE/checkins")
    lists = await client_with_db_session.get("/api/v1/hashtags/kahve/lists")

    assert [item["id"] for item in checkins.json()] == [created.json()["id"]]
    assert lists.json() == []


async def test_the_hashtag_page_does_not_scale_query_count_with_result_size(
    client_with_db_session: AsyncClient,
    db_session: AsyncSession,
    query_counter: QueryCounter,
    author: User,
    venue: Venue,
) -> None:
    """Each check-in carries a mention, so resolving mentions per row
    would show up here as a growing query count.
    """
    ali = await create_user(db_session)
    await befriend(db_session, author, ali)

    async def page_queries() -> int:
        query_counter.reset()
        response = await client_with_db_session.get("/api/v1/hashtags/n1/checkins")
        assert response.status_code == 200
        return query_counter.count

    await post_checkin(db_session, author, venue, note=mentioning(ali, text="#n1"))
    small = await page_queries()
    for _ in range(_PAGE_GROWTH):
        await post_checkin(db_session, author, venue, note=mentioning(ali, text="#n1"))
    large = await page_queries()

    assert large == small
