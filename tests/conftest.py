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
# Same role split as production (ADR-0016 in obur-docs): the owner role
# above runs migrations/seeding even in tests (see
# tests/integration/conftest.py's `_prepared_test_database`), and this is
# the application role's connection, the one `app.core.database.engine`
# (and therefore every test that goes through the real app) actually
# uses. Fallback mirrors `_database_url`'s: matches docker-compose.yml's
# own un-overridden defaults plus the role the ADR-0016 migration creates,
# for a clean checkout with no `.env` yet.
_app_database_url: str = _env_file.get("APP_DATABASE_URL") or (
    "postgresql+asyncpg://obur_app:local-dev-only-not-a-real-secret@localhost:5432/obur"
)
_redis_url: str = _env_file.get("REDIS_URL") or "redis://localhost:6379/0"

_db_parts = urlsplit(_database_url)
_test_database_url = urlunsplit(_db_parts._replace(path=f"{_db_parts.path}_test"))
_app_db_parts = urlsplit(_app_database_url)
_test_app_database_url = urlunsplit(
    _app_db_parts._replace(path=f"{_app_db_parts.path}_test")
)
_test_redis_url = urlunsplit(urlsplit(_redis_url)._replace(path="/1"))

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", _test_database_url)
os.environ.setdefault("APP_DATABASE_URL", _test_app_database_url)
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

from app.core.redis import redis_client  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware.rate_limit import KEY_NAMESPACE  # noqa: E402


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired directly to the FastAPI app, no network involved."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def _reset_rate_limit_counters() -> AsyncGenerator[None, None]:
    """Give every test a fresh counter window.

    The limiter stays enabled rather than being stubbed out: it sits in the
    real middleware stack, so disabling it here would mean no test ever
    exercises the path a live request takes. Counters are per-caller and
    tests share one caller, so without this the suite spends its own quota
    and later tests get 429s that have nothing to do with what they assert.

    Only the limiter's own namespace is cleared — never `flushdb`, which
    would take the cache with it.
    """
    await _clear_rate_limit_counters()
    yield
    await _clear_rate_limit_counters()


async def _clear_rate_limit_counters() -> None:
    async for key in redis_client.scan_iter(match=f"{KEY_NAMESPACE}:*"):
        await redis_client.delete(key)
