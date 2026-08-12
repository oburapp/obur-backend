"""Tests for Redis connectivity checks."""

from unittest.mock import AsyncMock

from pytest_mock import MockerFixture
from redis.exceptions import RedisError

from app.core.redis import check_redis_connection


async def test_check_redis_connection_returns_true_when_ping_succeeds(
    mocker: MockerFixture,
) -> None:
    mocker.patch("app.core.redis.redis_client.ping", AsyncMock(return_value=True))

    result = await check_redis_connection()

    assert result is True


async def test_check_redis_connection_returns_false_on_redis_error(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "app.core.redis.redis_client.ping", AsyncMock(side_effect=RedisError("boom"))
    )

    result = await check_redis_connection()

    assert result is False
