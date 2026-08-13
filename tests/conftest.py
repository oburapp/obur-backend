"""Shared pytest fixtures."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values

# Test-only configuration, resolved before any `app.*` module is imported
# below (Settings() has no defaults for these — see app/core/config.py).
#
# If a local `.env` exists, derive test values from it so a port/credential
# override there (e.g. POSTGRES_PORT=5433, to dodge a collision with an
# already-running local Postgres) is honored automatically instead of
# silently pointing tests at the wrong port. If it doesn't exist (a clean
# CI checkout), fall back to values matching docker-compose.yml's own
# un-overridden defaults.
_env_file = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

_database_url: str = (
    _env_file.get("DATABASE_URL")
    or "postgresql+asyncpg://user:password@localhost:5432/obur"
)
_redis_url: str = _env_file.get("REDIS_URL") or "redis://localhost:6379/0"

_db_parts = urlsplit(_database_url)
_test_database_url = urlunsplit(_db_parts._replace(path=f"{_db_parts.path}_test"))
_test_redis_url = urlunsplit(urlsplit(_redis_url)._replace(path="/1"))

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", _test_database_url)
os.environ.setdefault("REDIS_URL", _test_redis_url)
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
# Never the real secrets from .env — Clerk verification is always mocked
# in tests (see docs/testing-strategy.md). CLERK_WEBHOOK_SECRET must still
# be validly formatted: svix.Webhook() validates the "whsec_..." shape at
# construction time, before any mock of its .verify() method takes effect.
os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_fake_for_tests")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_ZmFrZV93ZWJob29rX3NlY3JldA==")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired directly to the FastAPI app, no network involved."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
