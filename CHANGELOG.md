# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-08-19

### Added

- `FOLLOW` and `CLOSE_FRIEND` models — one-directional, no-approval
  following, plus a manually curated close-friends list (a subset of a
  user's own followers) that grants access to `close_friends`-visibility
  content. A close friend can never outlive the follow it depended on:
  the composite foreign key to `FOLLOW` cascades the removal
  automatically on unfollow
- Shared three-tier `visibility` (`public`/`close_friends`/`private`)
  replacing `CHECKIN.is_public`, extended identically to the new `LIST`
  and `VENUE_SAVE` models — one authorization function
  (`app.core.authz.can_view`) for all three
- `LIST`/`LIST_ITEM` models and full CRUD, including item add/move/remove
  with fractional-indexing ordering (`fractional-indexing` package) — an
  insert, move, or removal writes only the one row being changed
- `CHECKIN_LIKE`/`LIST_LIKE` and `CHECKIN_BOOKMARK`/`LIST_BOOKMARK`
  models — likes are a visible signal, bookmarks are always private with
  no exposed count; both require the actor to already be able to see the
  target
- `NOTIFICATION` model, created synchronously in the same transaction as
  the triggering action (new follower, check-in like, list like) — no
  queue or background worker; `read_at` lives on the backend row for
  automatic cross-device consistency
- Endpoints for all of the above: follow/unfollow/followers/following,
  close-friends add/remove/list, list CRUD + items + like + bookmark,
  check-in like + bookmark, venue-save CRUD, and notification
  list/unread-count/mark-all-read
- `app.core.authz.ensure_visible_and_owned`: a shared guard for every
  owner-gated mutation (`CHECKIN`, `LIST`, `VENUE_SAVE` update/delete)
  that checks visibility before ownership, so a non-owner who can't even
  see a resource gets the same 404 a nonexistent id would — never a 403
  that would leak the id's existence

### Fixed

- A stranger `PATCH`ing or `DELETE`ing a private check-in, list, or
  venue save they don't own got a 403 (confirming the resource exists)
  instead of the 404 a nonexistent id would get, contradicting this
  codebase's own stated design goal that a hidden resource must be
  indistinguishable from a nonexistent one. Found via adversarial
  testing, not a bug report; fixed uniformly across all three resource
  types via `ensure_visible_and_owned` (see Added above)
- Listing a user's bookmarked check-ins/lists returned entries whose
  target had since been made private (or soft-deleted) by its owner,
  even though the bookmarker could no longer actually view them —
  bookmark listings now re-check visibility at read time, not just at
  bookmark time
- `venue_saves.type` had no database-level constraint on its allowed
  values, unlike `visibility` on the same table — added a `CHECK`
  constraint matching the existing pattern
- `pyproject.toml`'s coverage config was missing
  `concurrency = ["greenlet"]`; without it, coverage.py silently
  undercounted exception branches inside integration tests, since
  SQLAlchemy's async engine bridges sync DBAPI calls into the event loop
  via `greenlet_spawn`

## [0.4.0] - 2026-08-18

### Added

- `CHECKIN`, `CHECKIN_PRODUCT` models — a visit and its rated products,
  created together in one transaction. A product can't be rated twice
  in the same check-in; deleting a check-in is a soft delete, so a
  badge or aggregate rating already computed from it can't be
  retroactively corrupted
- `USER.role` (`user` | `admin`) and an ownership/admin authorization
  layer (`app/core/authz.py`): a user may act on their own check-ins,
  an admin on anyone's. Never settable through any endpoint — the first
  admin account is set directly in the database, by hand
- `POST/GET/PATCH/DELETE /api/v1/checkins/{id}`,
  `GET /api/v1/venues/{id}/checkins`, `GET /api/v1/users/{id}/checkins`
  — a private check-in is invisible to anyone but its owner or an
  admin, indistinguishable from a nonexistent one
- `DELETE /api/v1/admin/checkins/{id}` — admin-only permanent deletion,
  a separate endpoint from the regular (always-soft) delete so a
  destructive, irreversible action can't be triggered by accident

### Fixed

- Several foreign key columns had no index despite being filtered in
  real queries (`venues.added_by`/`category_id`,
  `products.venue_id`/`global_type_id`, `venue_categories.parent_id`,
  `global_product_types.category_id`,
  `venue_saves.user_id`/`venue_id`)

## [0.3.0] - 2026-08-13

### Added

- `VENUE`, `PRODUCT`, `VENUE_CATEGORY`, `GLOBAL_PRODUCT_TYPE`, and
  `VENUE_SAVE` models, with hierarchical categories and a
  translation-table pattern for multi-language display names
- Seed data for the initial venue category and product type catalog
  (Turkish), with one file per locale so adding a new language needs no
  code changes elsewhere
- Duplicate-venue detection: a new venue within 50 meters of an existing
  one is flagged before insert, so the client can prompt "did you mean
  this one?" instead of creating a near-duplicate
- Venue name search using PostgreSQL trigram similarity, tolerant of
  typos, partial input, and names typed without Turkish diacritics —
  chosen over language-specific full-text search to work uniformly
  across languages as the platform expands beyond Turkish
- `POST/GET /api/v1/venues`, `GET /api/v1/venues/{id}`
- `POST/GET /api/v1/products`, `GET /api/v1/products/{id}`

## [0.2.0] - 2026-08-13

### Added

- `USER` model, with provider-agnostic `auth_provider` / `auth_provider_id`
  identity fields, and its initial migration
- Clerk session token verification (`app/core/security.py`)
- `get_current_user` auth dependency, with JIT user provisioning as a
  fallback
- Clerk webhook endpoint (`user.created` / `.updated` / `.deleted`) with
  Svix signature verification, keeping `User` rows in sync
- `GET /api/v1/users/me`
- `just` task runner for common dev commands (lint, format, typecheck,
  test, local infra, migrations)

## [0.1.0] - 2026-08-13

### Added

- Development guide (`CLAUDE.md`)
- Project structure reference (`docs/project-structure.md`)
- Environment variable reference (`.env.example`)
- FastAPI application skeleton with a `/health` endpoint that verifies real
  PostgreSQL and Redis connectivity
- Async SQLAlchemy engine and session management for PostgreSQL + PostGIS
- Redis client and connectivity check
- Docker Compose local development environment (PostgreSQL+PostGIS, Redis)
  with configurable host ports to avoid local port collisions
- Alembic migrations, wired to the application's models and settings
- Unit and integration test suite (98% coverage enforced), with a
  dedicated `obur_test` database kept in sync via automatic migrations
- Testing strategy documentation (`docs/testing-strategy.md`)
- Configuration standards documenting the production-vs-local-only rule
  for environment values

### Changed

- Formatter switched from Black to `ruff format`
