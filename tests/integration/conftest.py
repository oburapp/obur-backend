"""Fixtures specific to integration tests."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import engine, get_session
from app.main import app
from app.seeds.runner import seed_catalog

_ALEMBIC_INI_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


async def _seed_reference_data() -> None:
    """Seed on a throwaway engine, disposed before the tests start.

    Deliberately not `app.core.database.engine`: this runs inside its own
    short-lived event loop (see the fixture below), and binding the shared
    engine's pooled connections to a loop that is about to close would hand
    a later test a connection tied to a dead loop.
    """
    seed_engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(seed_engine, expire_on_commit=False)() as session:
            await seed_catalog(session)
    finally:
        await seed_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _prepared_test_database() -> None:
    """Bring `obur_test` to head and seed its reference catalog.

    Runs once per test session. Targets `obur_test` because the root
    conftest.py already points DATABASE_URL there before any `app.*`
    module — including `migrations/env.py`'s settings lookup — is
    imported. Both halves are idempotent: a database already at head is a
    no-op, and the seeder upserts.

    Deliberately a *sync* fixture. `command.upgrade` drives an async
    migration environment through its own `asyncio.run()`, which raises if
    it is called from inside a running loop — so this must not be an async
    fixture, and the seed step gets its own `asyncio.run()` for the same
    reason.

    The seed step is not optional. Reference data lives in a seeder rather
    than a migration (ADR-0012), so migrating alone leaves
    `venue_categories` empty — and `VENUE.category_id` is `NOT NULL`, so
    every venue-touching test would fail on a fresh database. Schema and
    reference data are one setup step here for the same reason `just
    setup-db` chains them.
    """
    command.upgrade(Config(str(_ALEMBIC_INI_PATH)), "head")
    asyncio.run(_seed_reference_data())


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A session bound to one connection and one outer transaction that's
    rolled back after the test, so nothing a test writes leaks into the
    next one.

    `join_transaction_mode="create_savepoint"` makes a service's internal
    `session.commit()` release a SAVEPOINT instead of committing the outer
    transaction — see SQLAlchemy's "Joining a Session into an External
    Transaction" pattern.
    """
    async with engine.connect() as connection:
        await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,  # matches app.core.database's session factory
        )
        try:
            yield session
        finally:
            await session.close()
            await connection.rollback()


class QueryCounter:
    """Counts SQL statements executed on a connection, resettable
    mid-test so a setup phase's queries don't pollute the measurement.
    See docs/testing-strategy.md's N+1 query prevention section.
    """

    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0

    def _on_execute(self, *_args: object, **_kwargs: object) -> None:
        self.count += 1


@pytest.fixture
def query_counter(db_session: AsyncSession) -> Generator[QueryCounter, None, None]:
    """A `QueryCounter` wired to `db_session`'s own connection — use
    `.reset()` right before the operation under test, then assert on
    `.count` (typically: unchanged as the result set grows).
    """
    counter = QueryCounter()
    sync_connection = db_session.bind.sync_connection  # type: ignore[union-attr]
    event.listen(sync_connection, "before_cursor_execute", counter._on_execute)
    try:
        yield counter
    finally:
        event.remove(sync_connection, "before_cursor_execute", counter._on_execute)


@pytest.fixture
async def client_with_db_session(
    client: AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[AsyncClient, None]:
    """The shared `client` fixture, wired to `db_session` so an endpoint
    call and a direct DB assertion in the same test share (and roll back)
    one transaction.
    """
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        yield client
    finally:
        del app.dependency_overrides[get_session]
