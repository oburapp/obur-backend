# Backend Roadmap

Phased build order for `obur-backend`. Milestone-level, not task-level —
granular work items belong in GitHub Issues, not here. Phases are ordered
by dependency: each one unblocks the next, so building out of order creates
rework. See [pdd/obur-pdd.md](https://github.com/oburapp/obur-docs/blob/main/pdd/obur-pdd.md)
for the product rationale behind each domain.

## Phase 0 — Bootstrap

- `uv init`, `pyproject.toml`, core dependencies (fastapi, uvicorn, sqlalchemy[asyncio], alembic, asyncpg, pydantic-settings, redis, boto3)
- `app/` skeleton per [project-structure.md](project-structure.md)
- `docker-compose.yml`: PostgreSQL + PostGIS, Redis
- `app/core/config.py` (pydantic-settings reading `.env.example` keys)
- `app/main.py`: FastAPI app, lifespan, `/health` checking real DB + Redis connectivity
- Alembic initialized, first (empty) migration applies cleanly

**Why first:** nothing else runs without a working app + DB connection + migration pipeline.

## Phase 1 — Identity & Auth

- `USER` model + first real migration
- Clerk JWT verification middleware (`app/core/security.py`)
- Auth dependency for protected routes; public routes explicitly marked
- `GET /api/v1/users/me`

**Why now:** every other domain has a `user_id` FK and needs a verified identity to attach writes to.

## Phase 2 — Venues & Products

- `VENUE_CATEGORY` (+ translation), `GLOBAL_PRODUCT_TYPE` (+ translation), `VENUE`, `PRODUCT`, `VENUE_SAVE` models
- Venue creation with 50m-radius duplicate detection (PostGIS)
- Venue search (PostgreSQL FTS, Turkish config)
- `GET/POST /api/v1/venues`, `GET/POST /api/v1/products`

**Why now:** check-ins reference a venue and its products — this domain has to exist before check-ins can.

## Phase 3 — Check-in Core Loop

- `CHECKIN`, `CHECKIN_PRODUCT` models
- Create-checkin service: one `CHECKIN` + N `CHECKIN_PRODUCT` rows in a single transaction
- `POST /api/v1/checkins`, `GET /api/v1/venues/{id}/checkins`, `GET /api/v1/users/{id}/checkins`

**Why now:** this is the product's core action (PDD §10) and the dependency root for aggregate scoring, badges, and feed — build and stabilize it before anything downstream consumes it.

## Phase 4 — Social Graph & Engagement

- `FOLLOW`, `LIKE`, `LIST`, `LIST_ITEM` models
- Follow/unfollow, followers/following endpoints
- Like/unlike a check-in
- List CRUD

**Why now:** depends on both USER (Phase 1) and CHECKIN (Phase 3) existing; feeds in Phase 6 depend on FOLLOW.

## Phase 5 — Badges & Aggregate Scoring

- Aggregate rating labels per PDD §8 thresholds (venue/product pages)
- `BADGE`, `BADGE_TRANSLATION`, `USER_BADGE` models
- Badge award evaluation + periodic `rarity_pct` recalculation

**Why now:** both are read-derived from CHECKIN data — needs Phase 3 populated to be testable with real-shaped data.

## Phase 6 — Feed & Discovery

- Main feed: followed-users layer + algorithmic fill layer (PDD §12)
- Discover search: venue / product / user / list, ranking signals

**Why now:** the feed algorithm's signals (ratings, likes, follows) only make sense once Phases 3–5 exist.

## Phase 7 — Storage, Rate Limiting & Ops Polish

- R2 photo upload for check-ins, signed URLs
- Redis-based rate limiting on public endpoints
- Pagination audit across all list endpoints
- `GZipMiddleware`, graceful shutdown (dispose engine, close HTTP clients)

**Why now:** these are cross-cutting concerns best retrofitted once the real endpoint surface exists, rather than guessed at upfront.

## Phase 8 — Testing & Deployment Readiness

- Unit tests to the 98% coverage bar per service
- Integration tests: auth, check-in creation, venue search
- `docs/deployment.md` written against the real Railway setup
- First tagged release, `CHANGELOG.md` moves `[Unreleased]` → `[0.1.0]`

**Why last:** deployment docs and coverage targets are only meaningful once there's a real, working surface to document and test.
