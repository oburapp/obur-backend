# obur-backend

The REST API behind Obur, a taste-based social platform for restaurants,
cafés, and bars — people log where they went and what they thought, and
discover places through the people whose taste they trust rather than an
anonymous crowd average.

This service is the only backend for both clients (`obur-web`,
`obur-mobile`). It owns the data model, authorization, and every read the
clients make. FastAPI on PostgreSQL + PostGIS, with Clerk for identity,
Redis for caching and rate limiting, and Cloudflare R2 for photos.

- **Product rationale and data model:** [obur-docs/pdd/obur-pdd.md](https://github.com/oburapp/obur-docs/blob/main/pdd/obur-pdd.md)
- **Architecture decisions:** [obur-docs/adr/](https://github.com/oburapp/obur-docs/blob/main/adr/README.md)
- **Build order and current phase:** [docs/roadmap.md](docs/roadmap.md)
- **Conventions for working in this repo:** [CLAUDE.md](CLAUDE.md)

---

## Local setup

Requires [uv](https://docs.astral.sh/uv/), Docker, and
[just](https://github.com/casey/just).

```bash
cp .env.example .env     # then fill in the values it lists
uv sync                  # install dependencies into .venv
just up                  # start PostgreSQL + PostGIS and Redis
just setup-db            # apply migrations, then seed the reference catalog
```

`just setup-db` is two steps on purpose. Migrations own the schema; the
reference catalog (venue categories and their translations) is applied
separately by an idempotent seeder, because it describes what the catalog
should contain *now* and is expected to grow — see
[ADR-0012](https://github.com/oburapp/obur-docs/blob/main/adr/0012-migrations-are-self-contained-reference-data-is-seeded.md).
Migrating without seeding leaves `venue_categories` empty, and
`VENUE.category_id` is `NOT NULL`, so venue creation will fail.

Re-run `just seed` on its own after editing anything under `app/seeds/`.

## Running

```bash
just dev                 # uvicorn with auto-reload on http://127.0.0.1:8000
```

Interactive API docs are at `/docs`, and `/health` performs real
PostgreSQL and Redis connectivity checks rather than returning a
hard-coded 200.

## Tests

```bash
just test                # full suite with coverage
just check               # lint + typecheck + test — what CI runs
```

Unit tests mock every external dependency and need no infrastructure.
Integration tests run against a real `obur_test` database, created
automatically by the Docker container and migrated and seeded by a session
fixture — so `just up` is the only prerequisite. Each one runs inside a
transaction that is rolled back afterwards, so tests never see each other's
writes. Coverage minimum is 98%. See
[docs/testing-strategy.md](docs/testing-strategy.md).

## Common commands

Run `just --list` for everything. The ones worth knowing:

| Command | What it does |
|---|---|
| `just check` | lint + typecheck + test |
| `just up` / `just down` | start / stop local infrastructure |
| `just nuke` | stop infrastructure **and wipe all data** |
| `just setup-db` | migrate, then seed |
| `just migration "message"` | scaffold a migration from model changes |
| `just migrate-check` | detect schema drift without applying anything |

## Environment variables

Every variable is listed in [.env.example](.env.example). `.env` itself is
never committed.

Values that reach production — `DATABASE_URL`, `REDIS_URL`, `CORS_ORIGINS`,
`ENVIRONMENT`, `CLERK_SECRET_KEY` — have **no fallback**: a missing one
fails at startup rather than quietly resolving to a plausible-looking
localhost value. Variables for integrations not yet wired up default to an
empty string, an honest "not configured" marker; each becomes required in
the same change that starts using it.

## Project structure

See [docs/project-structure.md](docs/project-structure.md). In short:
`app/api/v1/` holds routers, `app/services/` holds business logic and every
database query, `app/models/` and `app/schemas/` hold the ORM models and
their Pydantic request/response counterparts. Routers never query the
database directly.
