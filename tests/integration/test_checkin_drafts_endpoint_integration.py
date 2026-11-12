"""End-to-end tests for `/api/v1/checkin-drafts` and the idempotency
contract of `POST /api/v1/checkins` (ADR-0018 in obur-docs): real
database, real routing, real problem mapping, no mocks.
"""

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import set_current_user_identity
from app.core.idempotency import IDEMPOTENCY_KEY_HEADER
from app.main import app
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from tests.integration.conftest import override_current_user

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_DRAFTS = "/api/v1/checkin-drafts"
_CHECKINS = "/api/v1/checkins"
_PROBLEM = "urn:obur:problem:"


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


@pytest.fixture
async def user(db_session: AsyncSession) -> AsyncGenerator[User, None]:
    """A user every request in the test is authenticated as."""
    created = await _create_user(db_session)
    app.dependency_overrides[get_current_user] = override_current_user(
        created, db_session
    )
    yield created
    del app.dependency_overrides[get_current_user]


@pytest.fixture
async def venue(db_session: AsyncSession, user: User) -> Venue:
    await set_current_user_identity(db_session, user.id)
    created = Venue(
        name="Balat Kahvesi",
        lat=41.0294,
        lng=28.9487,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )
    db_session.add(created)
    await db_session.flush()
    return created


def _checkin_body(venue: Venue, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "venue_id": str(venue.id),
        "rating_taste": 4,
        "rating_service": 3,
        "rating_ambiance": 3,
        "rating_value": 2,
        "visited_at": date.today().isoformat(),
        "visited_tz": "Europe/Istanbul",
    }
    body.update(overrides)
    return body


async def test_draft_lifecycle_create_autosave_list_and_delete(
    client_with_db_session: AsyncClient, user: User, venue: Venue
) -> None:
    created = await client_with_db_session.post(_DRAFTS, json={})
    assert created.status_code == 201
    draft = created.json()
    assert draft["visibility"] == "public"

    saved = await client_with_db_session.patch(
        f"{_DRAFTS}/{draft['id']}",
        json={"venue_id": str(venue.id), "visibility": "close_friends"},
    )
    assert saved.status_code == 200
    assert saved.json()["visibility"] == "close_friends"

    listed = await client_with_db_session.get(_DRAFTS)
    assert [item["id"] for item in listed.json()] == [draft["id"]]

    fetched = await client_with_db_session.get(f"{_DRAFTS}/{draft['id']}")
    assert fetched.json()["venue_id"] == str(venue.id)

    deleted = await client_with_db_session.delete(f"{_DRAFTS}/{draft['id']}")
    assert deleted.status_code == 204
    gone = await client_with_db_session.get(f"{_DRAFTS}/{draft['id']}")
    assert gone.status_code == 404
    assert gone.json()["type"] == f"{_PROBLEM}checkin-draft-not-found"


async def test_autosave_rejects_a_visit_date_without_its_timezone(
    client_with_db_session: AsyncClient, user: User
) -> None:
    draft = (await client_with_db_session.post(_DRAFTS, json={})).json()

    response = await client_with_db_session.patch(
        f"{_DRAFTS}/{draft['id']}", json={"visited_at": date.today().isoformat()}
    )

    assert response.status_code == 422


async def test_submitting_a_checkin_from_a_draft_removes_the_draft(
    client_with_db_session: AsyncClient, user: User, venue: Venue
) -> None:
    draft = (await client_with_db_session.post(_DRAFTS, json={})).json()

    response = await client_with_db_session.post(
        _CHECKINS,
        headers={IDEMPOTENCY_KEY_HEADER: str(uuid4())},
        json=_checkin_body(venue, draft_id=draft["id"]),
    )

    assert response.status_code == 201
    gone = await client_with_db_session.get(f"{_DRAFTS}/{draft['id']}")
    assert gone.status_code == 404


async def test_a_replayed_submission_returns_the_same_201_and_checkin(
    client_with_db_session: AsyncClient, user: User, venue: Venue
) -> None:
    headers = {IDEMPOTENCY_KEY_HEADER: str(uuid4())}

    first = await client_with_db_session.post(
        _CHECKINS, headers=headers, json=_checkin_body(venue)
    )
    replay = await client_with_db_session.post(
        _CHECKINS, headers=headers, json=_checkin_body(venue)
    )

    assert first.status_code == replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]


async def test_a_key_reused_with_different_content_returns_422(
    client_with_db_session: AsyncClient, user: User, venue: Venue
) -> None:
    headers = {IDEMPOTENCY_KEY_HEADER: str(uuid4())}
    await client_with_db_session.post(
        _CHECKINS, headers=headers, json=_checkin_body(venue, rating_taste=4)
    )

    response = await client_with_db_session.post(
        _CHECKINS, headers=headers, json=_checkin_body(venue, rating_taste=1)
    )

    assert response.status_code == 422
    assert response.json()["type"] == f"{_PROBLEM}idempotency-key-reused"


@pytest.mark.parametrize(
    ("headers", "expected_type"),
    [
        ({}, "idempotency-key-missing"),
        ({IDEMPOTENCY_KEY_HEADER: "not-a-uuid"}, "idempotency-key-invalid"),
    ],
)
async def test_a_missing_or_malformed_key_returns_400(
    client_with_db_session: AsyncClient,
    user: User,
    venue: Venue,
    headers: dict[str, str],
    expected_type: str,
) -> None:
    response = await client_with_db_session.post(
        _CHECKINS, headers=headers, json=_checkin_body(venue)
    )

    assert response.status_code == 400
    assert response.json()["type"] == f"{_PROBLEM}{expected_type}"


async def test_an_unauthenticated_submission_gets_401_not_a_header_error(
    client_with_db_session: AsyncClient,
) -> None:
    response = await client_with_db_session.post(_CHECKINS, json={})

    assert response.status_code == 401


async def test_an_unknown_timezone_is_a_422_not_a_server_error(
    client_with_db_session: AsyncClient, user: User, venue: Venue
) -> None:
    """Before validation, an unknown `visited_tz` reached `ZoneInfo` in the
    service and surfaced as an unhandled 500.
    """
    checkin = await client_with_db_session.post(
        _CHECKINS,
        headers={IDEMPOTENCY_KEY_HEADER: str(uuid4())},
        json=_checkin_body(venue, visited_tz="Mars/Olympus"),
    )
    draft = await client_with_db_session.post(
        _DRAFTS,
        json={"visited_at": date.today().isoformat(), "visited_tz": "Mars/Olympus"},
    )

    assert checkin.status_code == 422
    assert draft.status_code == 422
    assert checkin.json()["type"] == f"{_PROBLEM}validation-failed"
