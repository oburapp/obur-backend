# CLAUDE.md — obur-backend

## Project Overview

Obur backend is a production REST API serving both the web and mobile clients.
Built with FastAPI and PostgreSQL. Handles authentication via Clerk JWT tokens,
file storage via Cloudflare R2, and location-based queries via PostGIS.

For shared Git, branching, commit, and documentation standards, see
[obur-docs/CLAUDE.md](https://github.com/oburapp/obur-docs/blob/main/CLAUDE.md).
Read it first if you haven't already.

For product decisions, data model, and architectural context, see
[obur-docs/pdd/obur-pdd.md](https://github.com/oburapp/obur-docs/blob/main/pdd/obur-pdd.md).

At the start of every session, check `docs/adr/README.md` in obur-docs for the ADR index.
Only open individual ADR files when the relevant topic comes up — not all at once.

For build order and current phase, see [docs/roadmap.md](docs/roadmap.md).

Common commands are wrapped in the `justfile` — run `just --list` to see
them (lint, format, typecheck, test, `check` for all three, `up`/`down`
for local infra, `migrate`/`migration`). See [obur-docs/CLAUDE.md](https://github.com/oburapp/obur-docs/blob/main/CLAUDE.md#task-runner)
for the cross-repo convention.

---

## Tech Stack

- **Runtime:** Python 3.12+
- **Framework:** FastAPI + Uvicorn
- **ORM:** SQLAlchemy (async) + Alembic
- **Database:** PostgreSQL 16 + PostGIS
- **Auth:** Clerk (JWT verification via middleware)
- **Storage:** Cloudflare R2 (boto3 / S3-compatible)
- **Cache:** Redis
- **Package manager:** uv
- **Search:** PostgreSQL FTS (initial) → Meilisearch (when needed)

---

## Project Structure

See [docs/project-structure.md](docs/project-structure.md) for the target
directory layout.

---

## General Rules

- Always use type annotations — Python 3.12+ syntax throughout
- Use `X | None` instead of `Optional[X]`
- Use `X | Y` instead of `Union[X, Y]`
- No magic numbers or strings — define as named constants
- No `TODO` comments — fix it now or open a GitHub issue
- No commented-out code in commits
- No `print()` — always use the logger
- No bare `except` — always catch specific exceptions
- No `assert` for runtime validation — raise proper exceptions
- No `global` variables
- No mutable default arguments
- No `from module import *`
- No hardcoded URLs, ports, or credentials
- Every module must have a docstring explaining what it does
- Every function and method must have type annotations on all parameters and return type

---

## Code Style

- Follow PEP 8, formatted with `ruff format`
- Max line length: 88 characters
- Import order: stdlib → third-party → local (enforced via ruff's `I` rules)
- Use f-strings, never `.format()` or `%`
- Prefer list comprehensions but never sacrifice readability
- Max function length: 30 lines — if scrolling is needed, split it
- Even under 30 lines: if there are deeply nested conditions or loops, split it
- Cyclomatic complexity limit enforced via ruff C901

```python
# correct
async def get_venue_checkins(
    venue_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[CheckinResponse]: ...


# wrong
async def get_venue_checkins(venue_id, limit=20, offset=0): ...
```

---

## Type Annotations

- All function parameters and return types must be annotated
- Use Pydantic models for all validation — never TypedDict or dataclass
- Use `UUID` from `uuid` for all ID fields, never `str` or `int`

```python
# correct
async def create_checkin(
    user_id: UUID,
    payload: CheckinCreateRequest,
    session: AsyncSession,
) -> CheckinResponse: ...


# wrong
async def create_checkin(user_id, payload, session): ...
```

---

## Error Handling

- Define custom exception classes per service domain
- Catch specific exceptions, never bare `except`
- Log errors but never log sensitive data (tokens, user PII, API keys)
- User-facing error messages must be clear and non-technical
- Use `raise ... from e` when wrapping exceptions to preserve the chain
- Use plain `raise` (no argument) to re-raise the same exception after cleanup (e.g. rollback)
- Add `try/except` only when both conditions are true:
  1. There is real I/O (network, DB, external API, file)
  2. There is a meaningful action to take on failure (rollback, fallback, user message)
- Never add `try/except` around pure config loading or object construction — fail fast there

```python
# correct
try:
    result = await r2_client.upload(file)
except ClientError as e:
    logger.error("R2 upload failed: %s", e)
    raise StorageError("File could not be uploaded") from e

# wrong
try:
    result = await r2_client.upload(file)
except:
    pass
```

---

## Async Rules

- All FastAPI endpoints must be `async def`
- All DB operations use async SQLAlchemy sessions
- Use `httpx.AsyncClient` for all outbound HTTP calls — never `requests`
- Never use `time.sleep()` — use `asyncio.sleep()`
- Never write an `async def` function without an `await` inside
- CPU-bound operations must run via `asyncio.run_in_executor`

---

## Database

- Never write raw SQL — always use SQLAlchemy ORM
- Every DB operation must be inside a transaction
- Use Alembic for all schema changes — never modify the DB directly
- Always think about indexes — every FK and every filtered column needs one
- Use `joinedload` or `selectinload` explicitly when fetching related data — never rely on lazy loading
- Always use async context manager for sessions: `async with session_factory() as session`
- Never call `session.close()` manually
- Never return ORM objects directly from endpoints — always map to a Pydantic response schema
- For bulk inserts/updates, never loop with individual statements — use bulk operations:
  - Stable identity (e.g. `google_places_id`) → bulk upsert (`INSERT ... ON CONFLICT DO UPDATE`)
  - Ephemeral data → truncate-and-load
- Migration rules:
  - Unapplied migration files may be edited (autogenerate is imperfect)
  - Already-applied migrations must never be modified — write a new migration instead
  - Before modifying an applied migration, explain why and get approval first

---

## API Design

- Follow RESTful principles
- All endpoints live under `/api/v1/`
- Every endpoint must have explicit request and response Pydantic schemas
- Use correct HTTP status codes:
  - `200` — success
  - `201` — created
  - `400` — client error
  - `401` — unauthorized
  - `403` — forbidden
  - `404` — not found
  - `422` — validation error
  - `500` — server error
- All list endpoints must support pagination (limit/offset or cursor-based) — never return unbounded results
- Enable `GZipMiddleware` for response compression
- Use FastAPI `Depends()` for dependency injection — never instantiate services manually as globals
- `/health` endpoint must perform real dependency checks (PostgreSQL, Redis) — not just return 200
- Implement graceful shutdown in `lifespan`: dispose DB engine, close HTTP clients, drain background tasks

```python
# wrong
search_service = SearchService()  # global


# correct
async def get_search_service(
    session: AsyncSession = Depends(get_session),
) -> SearchService:
    return SearchService(session)


@router.get("/venues/{venue_id}/checkins")
async def list_checkins(
    venue_id: UUID,
    service: CheckinService = Depends(get_checkin_service),
) -> list[CheckinResponse]: ...
```

---

## Authentication

- Clerk issues JWTs — verify via middleware on every protected endpoint
- Never trust client-supplied user IDs — always extract from the verified JWT
- Public endpoints (read-only discovery, health) must be explicitly marked
- Middleware must reject requests with invalid or expired tokens before they reach route handlers

---

## Storage (Cloudflare R2)

- Never store files locally in production — always upload to R2
- Always validate file type and size before upload
- Generate unique object keys — never use user-supplied filenames directly
- Signed URLs for private assets — never expose bucket URLs directly
- Clean up orphaned objects when the associated DB record is deleted

---

## Caching (Redis)

- Cache keys must be namespaced: `checkin:{id}`, `venue:{id}:aggregate`
- Always set TTL — never cache without expiry
- Use `hashlib.sha256` for cache keys derived from text — never Python's built-in `hash()` (it is process-salted and non-deterministic across restarts)
- Invalidate cache on write — never serve stale data silently

```python
# correct
import hashlib

text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
cache_key = f"embed:{text_hash}"

# wrong
cache_key = f"embed:{hash(text)}"  # non-deterministic across restarts
```

---

## Location and Search

- All coordinates stored as `FLOAT` (lat, lng) — PostGIS used for proximity queries
- Duplicate venue detection: query for existing venues within 50m radius before insert
- Full-text search uses PostgreSQL FTS with Turkish language configuration
- When PostgreSQL FTS becomes a bottleneck, migrate to Meilisearch — document the decision as an ADR

---

## Configuration

See [obur-docs/CLAUDE.md](https://github.com/oburapp/obur-docs/blob/main/CLAUDE.md#environment-variables)
for the general production-vs-local-only rule. Concretely, in this repo:

- `Settings` fields (`app/core/config.py`) with no default are the
  production-reaching contract — `database_url`, `redis_url`,
  `cors_origins`, `environment`. Missing → `Settings()` raises immediately,
  it never falls back to a plausible-looking localhost value.
- Fields not yet consumed by any code path (`clerk_secret_key`, `r2_*`)
  default to `""` — an honest "not configured" sentinel, not a fake value.
  Make a field required in the same PR that starts actually using it, not
  before — a required field for an integration nobody has built yet just
  blocks the app from starting.
- Local dev infrastructure (`docker-compose.yml` ports, `POSTGRES_*`) reads
  from `.env` via `${VAR:-default}` — never a second hardcoded copy of a
  value `.env` already owns.
- Test-only config (`tests/conftest.py`) derives its test database/Redis
  URLs from the real `.env` (via `python-dotenv`) instead of hardcoding an
  independent value, so a local port override (e.g. to dodge a collision
  with an already-running Postgres) is honored automatically rather than
  silently pointing tests at the wrong place.

```python
# correct — fails fast, no plausible-looking fallback
database_url: str

# wrong — masks a missing/misconfigured .env
database_url: str = "postgresql+asyncpg://user:password@localhost:5432/obur"
```

---

## Testing

See [docs/testing-strategy.md](docs/testing-strategy.md) for the unit vs.
integration split and the test database setup.

- Test coverage minimum: **98%**
- Every service function must have unit tests
- Use fixtures for all shared state — tests must be fully independent
- Test names must describe exactly what they verify:

```python
# correct
async def test_create_checkin_returns_201_with_valid_payload(): ...


async def test_create_checkin_fails_with_missing_venue_id(): ...


# wrong
async def test_checkin(): ...
```

---

## Logging

- Never use `print()` — always use the Python `logging` module
- Log levels:
  - `DEBUG` — development details, verbose output
  - `INFO` — normal application flow
  - `WARNING` — unexpected but recoverable situation
  - `ERROR` — operation failed
- Never log: passwords, tokens, API keys, user PII, environment variable values
- Every log message must clearly describe what happened and where

---

## Security

- Always validate and sanitize user input
- Rate limiting active on all public endpoints (via Redis)
- Never expose stack traces or internal error details to clients
- Never log sensitive data
- API keys always read from environment — never hardcoded

---

## Package Management

- Always use `uv add` / `uv remove` — never `pip install` directly
- `uv.lock` must always be committed
- Never edit `pyproject.toml` outside of `uv` commands for dependencies

---

## File and Module Rules

- Every directory must have `__init__.py`
- File names in `snake_case`
- Max file length: 300 lines — split if exceeded
- No circular imports — design module boundaries to prevent them
- File paths must use `Path(__file__).parent / ...` — never relative to CWD
- DB queries belong in `app/services/` — never in route handlers
- No separate Repository layer for now — services handle queries directly; revisit if services grow large and queries are duplicated across multiple services

---

## Forbidden

- `global` variables
- Mutable default arguments
- `time.sleep()` — use `asyncio.sleep()`
- `from module import *`
- `TODO` comments
- Hardcoded URLs, ports, or credentials
- `assert` for runtime validation in production code
- Raw SQL outside of PostGIS-specific queries (and even then, use SQLAlchemy `text()` with bound parameters)
- Committing `.env` or any file containing secrets
- Returning ORM objects directly from endpoints
- Unbounded DB queries without pagination