"""Tests for application lifespan (startup/shutdown) behavior."""

from unittest.mock import AsyncMock, MagicMock

from pytest_mock import MockerFixture

from app.main import app, lifespan


async def test_lifespan_disposes_engine_and_closes_redis_on_shutdown(
    mocker: MockerFixture,
) -> None:
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    mock_redis_client = MagicMock()
    mock_redis_client.aclose = AsyncMock()

    mocker.patch("app.main.engine", mock_engine)
    mocker.patch("app.main.redis_client", mock_redis_client)

    async with lifespan(app):
        pass

    mock_engine.dispose.assert_awaited_once()
    mock_redis_client.aclose.assert_awaited_once()
