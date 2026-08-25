"""Unit tests for app.services.venue — every DB call is mocked."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import (
    DuplicateVenueNearbyError,
    VenueCategoryNotFoundError,
    VenueNotFoundError,
)
from app.models.venue import Venue
from app.models.venue_category import VenueCategory
from app.services import venue as venue_service

_DEFAULT = object()  # sentinel: "use a fresh MagicMock category", not None


def _session_with(
    get_result: object = _DEFAULT,
    execute_scalars_first: Venue | None = None,
    execute_scalars_all: list[Venue] | None = None,
) -> AsyncMock:
    if get_result is _DEFAULT:
        get_result = MagicMock(spec=VenueCategory)
    session = AsyncMock()
    session.add = MagicMock()  # AsyncSession.add() is sync, not a coroutine
    session.get = AsyncMock(return_value=get_result)
    result = MagicMock()
    result.scalars.return_value.first.return_value = execute_scalars_first
    result.scalars.return_value.all.return_value = execute_scalars_all or []
    session.execute.return_value = result
    return session


async def test_create_venue_raises_when_category_not_found() -> None:
    session = _session_with(get_result=None)

    with pytest.raises(VenueCategoryNotFoundError):
        await venue_service.create_venue(
            session,
            name="Karadeniz Pide",
            lat=41.0,
            lng=29.0,
            category_id=uuid4(),
            added_by=uuid4(),
            district="Kadıköy",
        )

    session.add.assert_not_called()


async def test_create_venue_raises_when_duplicate_within_radius() -> None:
    nearby = Venue(id=uuid4(), name="Existing Venue")
    session = _session_with(execute_scalars_first=nearby)

    with pytest.raises(DuplicateVenueNearbyError) as exc_info:
        await venue_service.create_venue(
            session,
            name="Karadeniz Pide",
            lat=41.0,
            lng=29.0,
            category_id=uuid4(),
            added_by=uuid4(),
            district="Kadıköy",
        )

    assert exc_info.value.nearby_venue_id == nearby.id
    session.add.assert_not_called()


async def test_create_venue_skips_duplicate_check_when_confirmed() -> None:
    nearby = Venue(id=uuid4(), name="Existing Venue")
    session = _session_with(execute_scalars_first=nearby)

    await venue_service.create_venue(
        session,
        name="Karadeniz Pide",
        lat=41.0,
        lng=29.0,
        category_id=uuid4(),
        added_by=uuid4(),
        district="Kadıköy",
        confirm_duplicate=True,
    )

    session.execute.assert_not_called()
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


async def test_create_venue_succeeds_with_no_nearby_duplicate() -> None:
    session = _session_with(execute_scalars_first=None)

    venue = await venue_service.create_venue(
        session,
        name="Karadeniz Pide",
        lat=41.0,
        lng=29.0,
        category_id=uuid4(),
        added_by=uuid4(),
        district="Kadıköy",
    )

    assert venue.name == "Karadeniz Pide"
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


async def test_get_venue_returns_venue_when_found() -> None:
    venue = Venue(id=uuid4(), name="Karadeniz Pide")
    session = _session_with(get_result=venue)

    result = await venue_service.get_venue(session, venue.id)

    assert result is venue


async def test_get_venue_raises_when_not_found() -> None:
    session = _session_with(get_result=None)

    with pytest.raises(VenueNotFoundError):
        await venue_service.get_venue(session, uuid4())


async def test_list_venues_returns_paginated_results() -> None:
    venues = [Venue(id=uuid4(), name="A"), Venue(id=uuid4(), name="B")]
    session = _session_with(execute_scalars_all=venues)

    result = await venue_service.list_venues(session, limit=20, offset=0)

    assert result == venues


async def test_search_venues_returns_matches() -> None:
    venues = [Venue(id=uuid4(), name="Kadıköy'de En İyi Döner")]
    session = _session_with(execute_scalars_all=venues)

    result = await venue_service.search_venues(session, "döner", limit=20, offset=0)

    assert result == venues
    # Once to set the similarity threshold, once for the search query.
    assert session.execute.await_count == 2
