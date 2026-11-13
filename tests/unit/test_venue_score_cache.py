"""Unit tests for app.services.venue_score's cache handling (ADR-0020 in
obur-docs): Redis failing or holding junk never fails the request.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

from pytest_mock import MockerFixture
from redis.exceptions import RedisError

from app.models.venue import Venue
from app.schemas.venue_score import CriteriaTiers, VenueScore
from app.services import venue_score

_SCORE = VenueScore(
    tier=None,
    criteria=CriteriaTiers(taste=None, service=None, ambiance=None, value=None),
    checkin_count=3,
)
_MODULE = "app.services.venue_score"


def _venue() -> Venue:
    return Venue(id=uuid4(), score_version=7)


async def test_a_redis_outage_falls_back_to_computing(mocker: MockerFixture) -> None:
    redis = mocker.patch(f"{_MODULE}.redis_client")
    redis.get = AsyncMock(side_effect=RedisError("down"))
    redis.set = AsyncMock(side_effect=RedisError("down"))
    compute = mocker.patch(
        f"{_MODULE}.compute_venue_score", AsyncMock(return_value=_SCORE)
    )

    score = await venue_score.get_venue_score(AsyncMock(), _venue())

    assert score == _SCORE
    compute.assert_awaited_once()


async def test_an_unreadable_cache_entry_is_recomputed(mocker: MockerFixture) -> None:
    redis = mocker.patch(f"{_MODULE}.redis_client")
    redis.get = AsyncMock(return_value="not json")
    redis.set = AsyncMock()
    mocker.patch(f"{_MODULE}.compute_venue_score", AsyncMock(return_value=_SCORE))

    score = await venue_score.get_venue_score(AsyncMock(), _venue())

    assert score == _SCORE
    redis.set.assert_awaited_once()


async def test_a_cached_entry_is_served_without_computing(
    mocker: MockerFixture,
) -> None:
    redis = mocker.patch(f"{_MODULE}.redis_client")
    redis.get = AsyncMock(return_value=_SCORE.model_dump_json())
    compute = mocker.patch(f"{_MODULE}.compute_venue_score", AsyncMock())
    venue = _venue()

    score = await venue_score.get_venue_score(AsyncMock(), venue)

    assert score == _SCORE
    compute.assert_not_awaited()
    redis.get.assert_awaited_once_with(f"venue:{venue.id}:score:v7")
