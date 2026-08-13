# Testing Strategy

Full context and rejected alternatives: [ADR-0001](https://github.com/oburapp/obur-docs/blob/main/adr/0001-test-database-strategy.md).

## Test tiers

**`tests/unit/`** — no real I/O. Every external dependency (database,
Redis, R2, Clerk, Mapbox) is mocked via `unittest.mock` / `pytest-mock`.
Fast, hermetic, safe to run with zero infrastructure running.

**`tests/integration/`** — exercises critical flows end-to-end through the
real app (checkin creation, venue search, auth). Runs against a real test
database (see below). Third-party services (R2, Clerk, Mapbox) are still
mocked here too — CI never makes real calls to the outside world.

This is a deliberate split, not a contradiction: unit tests prove the code
does what the mocks were told to return; integration tests prove the actual
SQL/PostGIS query is correct against a real database. A duplicate-venue
check built on `ST_DWithin` (see [ADR context in the PDD, §13](https://github.com/oburapp/obur-docs/blob/main/pdd/obur-pdd.md#13-venue-and-product-architecture))
is only actually verified by the second kind of test.

## Test database

Integration tests run against the same docker-compose Postgres+PostGIS
container used for local development, but against a separate `obur_test`
database so they never touch dev data.

Each integration test runs inside a transaction that's rolled back at the
end of the test, regardless of what the test wrote — the database is back
to its prior state before the next test runs. No `pytest-postgresql` or
other ephemeral-Postgres plugin is needed: the container is already there.

The `obur_test` database and its PostGIS extension are created by
`docker/postgres-init/20_create_test_database.sql` on first container
startup — nothing to set up manually.

`tests/conftest.py` derives the test DATABASE_URL/REDIS_URL from the real
`.env` (swapping in `obur_test` / a different Redis index) rather than
hardcoding them independently, so a local port override in `.env` (see
[Configuration](../CLAUDE.md#configuration)) is honored automatically
instead of silently pointing tests at the wrong port.

**Schema stays in sync automatically.** A test database only being created
once (at container init) isn't enough on its own — new migrations added
later wouldn't reach it. A session-scoped `autouse` fixture in
`tests/integration/conftest.py` runs `alembic upgrade head` against
`obur_test` at the start of every test session, so it's always at the
same schema version as the real migration history — nobody has to
remember to migrate it by hand, and it can never silently drift from what
`obur` (or production) actually has.

## N+1 query prevention

Every endpoint or service function that returns a list of ORM objects
*and* resolves related data through a SQLAlchemy `relationship()` (not
just a raw FK id) must have an integration test asserting the number of
SQL statements executed stays constant as the list grows — not only the
first such endpoint built, every one. A working `joinedload`/`selectinload`
call today doesn't guarantee the next person touching that code path
keeps it that way; a query-count assertion catches a regression to lazy
loading the same way a snapshot test catches an unintended output change.

Mechanism: a `db_session`-scoped fixture that counts statements via
SQLAlchemy's `before_cursor_execute` event, so a test can do something
like:

```python
async def test_list_venues_with_products_does_not_n_plus_1(
    db_session, query_counter
) -> None:
    # ... create N venues, each with products ...
    with query_counter() as count:
        await venue_service.list_venues_with_products(db_session, limit=20, offset=0)
    assert count() <= _EXPECTED_QUERY_COUNT  # constant, not O(N)
```

As of Phase 2 (Venues & Products), no model declares a `relationship()`
yet — every response schema serializes only scalar columns of the object
itself, so there's currently no code path where N+1 is possible, and no
`query_counter` fixture exists yet either. The first phase that adds a
`relationship()` and eager-loads it must also add this fixture (in
`tests/integration/conftest.py`) and the first test using it — from then
on, it applies to every relational list endpoint added after, not just
that first one.

## Coverage

Minimum 98%, enforced via `pytest-cov` (see `[tool.coverage]` in
`pyproject.toml`). Applies to the combined unit + integration suite.

## Fixtures

Shared fixtures live in `tests/conftest.py` (app-wide) or
`tests/integration/conftest.py` (test-database session, transaction
rollback). Tests must not share state — every test is independently
runnable and order-independent.

## Naming

Test names describe the exact scenario, not the function under test:

```python
# correct
async def test_create_checkin_returns_201_with_valid_payload(): ...
async def test_create_checkin_fails_with_missing_venue_id(): ...


# wrong
async def test_checkin(): ...
```
