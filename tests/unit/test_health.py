"""Tests for the /health endpoint."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app import main


async def test_health_returns_200_when_dependencies_are_healthy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "check_database_connection", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "check_redis_connection", AsyncMock(return_value=True))

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": True, "redis": True}


async def test_health_returns_503_when_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        main, "check_database_connection", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(main, "check_redis_connection", AsyncMock(return_value=True))

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": False, "redis": True}


async def test_health_returns_503_when_redis_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "check_database_connection", AsyncMock(return_value=True))
    monkeypatch.setattr(main, "check_redis_connection", AsyncMock(return_value=False))

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": True, "redis": False}
