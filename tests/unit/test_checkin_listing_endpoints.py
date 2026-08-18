"""Tests for GET /venues/{id}/checkins and GET /users/{id}/checkins —
the checkin service is mocked.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient
from pytest_mock import MockerFixture

from app.models.checkin import Checkin


def _checkin(**overrides: object) -> Checkin:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "venue_id": uuid4(),
        "rating_service": None,
        "rating_ambiance": None,
        "rating_value": None,
        "note": None,
        "photo_url": None,
        "is_public": True,
        "visited_at": date.today(),
        "visited_tz": "Europe/Istanbul",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Checkin(**defaults)


async def test_list_venue_checkins_returns_checkins(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    checkins = [_checkin(), _checkin()]
    mocker.patch(
        "app.api.v1.venues.checkin_service.list_checkins_for_venue",
        AsyncMock(return_value=checkins),
    )
    mocker.patch(
        "app.api.v1.venues.checkin_service.get_products_for_checkins",
        AsyncMock(return_value={}),
    )

    response = await client.get(f"/api/v1/venues/{uuid4()}/checkins")

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_list_user_checkins_returns_checkins(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    checkins = [_checkin()]
    mocker.patch(
        "app.api.v1.users.checkin_service.list_checkins_for_user",
        AsyncMock(return_value=checkins),
    )
    mocker.patch(
        "app.api.v1.users.checkin_service.get_products_for_checkins",
        AsyncMock(return_value={}),
    )

    response = await client.get(f"/api/v1/users/{uuid4()}/checkins")

    assert response.status_code == 200
    assert len(response.json()) == 1
