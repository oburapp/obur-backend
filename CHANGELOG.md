# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
