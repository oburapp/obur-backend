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

Every endpoint or service function that returns a list of items *and*
attaches each item's related data — whether via a SQLAlchemy
`relationship()` with `joinedload`/`selectinload`, or via a manual
batched fetch (e.g. one `WHERE parent_id IN (...)` query grouped in
Python) — must have an integration test asserting the number of SQL
statements executed stays constant as the list grows. Not just the
first such endpoint built: every one. Working eager-loading code today
doesn't guarantee the next person touching that code path keeps it that
way; a query-count assertion catches a regression to a per-row fetch the
same way a snapshot test catches an unintended output change.

Mechanism: `query_counter`, a fixture in `tests/integration/conftest.py`
wired to `db_session`'s own connection via SQLAlchemy's
`before_cursor_execute` event. Reset it right before the operation under
test, run the same operation against two differently-sized result sets,
and assert the count didn't grow:

```python
async def test_list_venue_checkins_does_not_scale_with_result_size(
    client_with_db_session, db_session, query_counter
) -> None:
    # ... create 1 check-in, then list them ...
    query_counter.reset()
    small = await client_with_db_session.get(f"/api/v1/venues/{venue_id}/checkins")
    small_count = query_counter.count

    # ... create 4 more check-ins, then list again ...
    query_counter.reset()
    large = await client_with_db_session.get(f"/api/v1/venues/{venue_id}/checkins")

    assert query_counter.count == small_count  # constant, not O(N)
```

Comparing two result sizes within the same test — rather than asserting
an exact count — sidesteps incidental per-session overhead (e.g. the
`SAVEPOINT` `db_session`'s transaction-joining mode issues on first use)
that would otherwise make a hardcoded expected count fragile.

First introduced in Phase 3 (Check-in Core Loop): `GET
/venues/{id}/checkins` batches each returned check-in's product ratings
in one `checkin_id IN (...)` query
(`app.services.checkin.get_products_for_checkins`) rather than querying
per check-in in a loop — see
`tests/integration/test_checkins_endpoint_integration.py`. No model
declares an ORM `relationship()` yet; when one first does, the same
fixture and the same comparative pattern apply, just against
`selectinload` instead of a hand-written batch query.

## Coverage

Minimum 98%, enforced via `pytest-cov` (see `[tool.coverage]` in
`pyproject.toml`). Applies to the combined unit + integration suite.

`[tool.coverage.run]` sets `concurrency = ["greenlet"]`. Without it,
coverage.py silently undercounts otherwise-executed lines inside
integration tests: SQLAlchemy's async engine bridges sync DBAPI calls
into the event loop via `greenlet_spawn`, and exception propagation
across that boundary (e.g. a service raising inside a `db_session`-backed
test) isn't tracked by the default tracer. Found empirically — a route's
`except` branch was verified to run correctly (the test asserted the
right HTTP status) while still showing as "missing" in the coverage
report, for every endpoint exercised only through `client_with_db_session`
rather than a mocked unit test.

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
