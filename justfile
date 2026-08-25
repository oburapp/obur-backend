# Run `just --list` (or just `just`) to see all recipes.
set minimum-version := "1.58.0"

# just defaults to looking for `sh`, which plain Windows PowerShell doesn't
# have on PATH. Recipes here are simple enough (no POSIX-only syntax) to
# run the same way under PowerShell.
[windows]
set shell := ["powershell.exe", "-NoProfile", "-Command"]

default:
    @just --list

# --- Code quality ---

# Lint the codebase
lint:
    uv run ruff check .

# Format the codebase
format:
    uv run ruff format .

# Check formatting without modifying anything (what CI runs)
format-check:
    uv run ruff format --check .

# Type-check the codebase
typecheck:
    uv run pyright

# Run the test suite with coverage
test:
    uv run pytest --cov --cov-report=term-missing

# Run lint + format-check + typecheck + test, the same checks CI runs
check: lint format-check typecheck test

# --- Local infrastructure ---

# Start Postgres+PostGIS and Redis
up:
    docker compose up -d

# Stop local infrastructure (keeps data)
down:
    docker compose down

# Stop local infrastructure and wipe all data (fresh init next `up`)
nuke:
    docker compose down -v

# Tail infrastructure logs
logs:
    docker compose logs -f

# --- Database ---

# Apply all pending migrations
migrate:
    uv run alembic upgrade head

# Create a new migration from model changes, e.g. `just migration "add venues table"`
migration message:
    uv run alembic revision --autogenerate -m "{{ message }}"

# Check for schema drift without applying anything
migrate-check:
    uv run alembic check

# Upsert the reference catalog (venue categories + translations).
# Idempotent — safe to re-run, and required after editing anything under
# app/seeds/. Runs alongside `migrate`, never from the app itself.
seed:
    uv run python -m app.seeds.runner

# Bring a database fully up to date: schema, then reference data
setup-db: migrate seed

# --- App ---

# Run the dev server with auto-reload
dev:
    uv run uvicorn app.main:app --reload
