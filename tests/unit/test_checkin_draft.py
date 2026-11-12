"""Unit tests for check-in draft schemas, service, and endpoints
(ADR-0018 in obur-docs). The database-backed behaviour (expiry, cleanup,
owner scoping, RLS) is covered by the integration suite.
"""

from collections.abc import Generator
from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import CheckinDraftNotFoundError, VenueNotFoundError
from app.main import app
from app.models.user import User
from app.schemas.checkin_draft import (
    CheckinDraftCreateRequest,
    CheckinDraftUpdateRequest,
)
from app.services import checkin_draft as draft_service

_TZ = "Europe/Istanbul"
_USER = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")
_SERVICE = "app.api.v1.checkin_drafts.draft_service"


@pytest.fixture
def _authenticated() -> Generator[None, None, None]:
    app.dependency_overrides[get_current_user] = lambda: _USER
    yield
    app.dependency_overrides.clear()


def test_create_request_defaults_visibility_to_public() -> None:
    assert CheckinDraftCreateRequest().visibility == "public"


def test_create_request_rejects_a_date_without_its_timezone() -> None:
    with pytest.raises(ValidationError):
        CheckinDraftCreateRequest(visited_at=date.today())


def test_update_request_rejects_clearing_visibility() -> None:
    with pytest.raises(ValidationError):
        CheckinDraftUpdateRequest(visibility=None)


def test_update_request_rejects_sending_only_one_visit_field() -> None:
    with pytest.raises(ValidationError):
        CheckinDraftUpdateRequest(visited_tz=_TZ)


def test_update_request_allows_clearing_both_visit_fields_together() -> None:
    cleared = CheckinDraftUpdateRequest(visited_at=None, visited_tz=None)

    assert cleared.model_dump(exclude_unset=True) == {
        "visited_at": None,
        "visited_tz": None,
    }


async def test_create_draft_refuses_an_unknown_venue_before_writing() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(VenueNotFoundError):
        await draft_service.create_draft(
            session, user_id=uuid4(), fields={"venue_id": uuid4()}
        )

    session.add.assert_not_called()


async def test_discard_submitted_draft_does_not_commit() -> None:
    session = AsyncMock()

    await draft_service.discard_submitted_draft(
        session, user_id=uuid4(), draft_id=uuid4()
    )

    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()


@pytest.mark.usefixtures("_authenticated")
async def test_get_draft_endpoint_returns_404_problem_for_a_missing_draft(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        f"{_SERVICE}.get_draft",
        AsyncMock(side_effect=CheckinDraftNotFoundError("nope")),
    )

    response = await client.get(f"/api/v1/checkin-drafts/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["type"] == "urn:obur:problem:checkin-draft-not-found"


@pytest.mark.usefixtures("_authenticated")
async def test_delete_draft_endpoint_returns_204(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    delete = mocker.patch(f"{_SERVICE}.delete_draft", AsyncMock(return_value=None))
    draft_id = uuid4()

    response = await client.delete(f"/api/v1/checkin-drafts/{draft_id}")

    assert response.status_code == 204
    delete.assert_awaited_once()
    assert delete.await_args is not None
    assert delete.await_args.kwargs == {"user_id": _USER.id, "draft_id": draft_id}


@pytest.mark.usefixtures("_authenticated")
async def test_list_drafts_endpoint_rejects_an_oversized_page(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/checkin-drafts", params={"limit": 10_000})

    assert response.status_code == 422


@pytest.mark.parametrize("name", ["Mars/Olympus", "", "../etc/passwd", "UTC+3"])
def test_draft_rejects_names_that_are_not_iana_timezones(name: str) -> None:
    with pytest.raises(ValidationError):
        CheckinDraftCreateRequest(visited_at=date.today(), visited_tz=name)


@pytest.mark.parametrize("name", [_TZ, "UTC", "America/Argentina/Buenos_Aires"])
def test_draft_accepts_real_iana_timezones(name: str) -> None:
    draft = CheckinDraftCreateRequest(visited_at=date.today(), visited_tz=name)

    assert draft.visited_tz == name
