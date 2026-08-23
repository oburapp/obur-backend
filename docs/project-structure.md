# Project Structure

Target directory layout for `obur-backend`. This is a planning reference —
once the structure exists in code, the actual filesystem is the source of
truth, not this file. Update this file when the top-level layout changes.

Entries marked `(Phase N)` don't exist yet; the number is the phase in
[roadmap.md](roadmap.md) that adds them. Everything unmarked is already in
the repository.

```
obur-backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── admin.py           # moderation surface, grows in Phase 10
│   │       ├── checkins.py
│   │       ├── close_friends.py
│   │       ├── follows.py
│   │       ├── lists.py
│   │       ├── notifications.py
│   │       ├── users.py
│   │       ├── venue_saves.py
│   │       ├── venues.py
│   │       ├── webhooks.py
│   │       ├── categories.py      # (Phase 6) venue-category catalog
│   │       ├── blocks.py          # (Phase 10)
│   │       ├── mutes.py           # (Phase 10)
│   │       ├── reports.py         # (Phase 10)
│   │       ├── checkin_drafts.py  # (Phase 11)
│   │       ├── hashtags.py        # (Phase 12)
│   │       ├── badges.py          # (Phase 14)
│   │       ├── media.py           # (Phase 15) upload endpoints
│   │       ├── feed.py            # (Phase 16)
│   │       └── discover.py        # (Phase 16)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── auth.py            # current-user dependency, JIT provisioning
│   │   ├── authz.py           # ownership, admin override, can_view
│   │   ├── config.py          # settings via pydantic-settings
│   │   ├── database.py        # async engine, session factory
│   │   ├── geo.py             # SRID and proximity constants
│   │   ├── i18n.py            # locale constants, translation resolution
│   │   ├── pagination.py      # shared page-size default and ceiling
│   │   ├── ratings.py         # the shared four-point scale
│   │   ├── redis.py           # redis client
│   │   ├── search.py          # trigram search helpers
│   │   ├── security.py        # clerk JWT verification
│   │   ├── user_identity.py   # handle/display-name defaults for new users
│   │   ├── visibility.py      # the shared three visibility tiers
│   │   ├── aggregates.py      # (Phase 13) confidence-bound scoring
│   │   └── media.py           # (Phase 15) EXIF strip, resize, signed URLs
│   ├── models/
│   │   ├── __init__.py        # re-exports Base + all model classes
│   │   ├── base.py            # shared SQLAlchemy declarative base
│   │   └── ...                # one module per resource (added as built)
│   ├── schemas/
│   │   └── __init__.py        # Pydantic request/response schemas, one module per resource
│   ├── services/
│   │   └── __init__.py        # business logic, DB queries, one module per resource
│   ├── exceptions/
│   │   └── __init__.py        # custom exceptions, one module per service domain
│   ├── seeds/
│   │   ├── __init__.py
│   │   ├── identity.py
│   │   ├── runner.py          # idempotent seeder — `just seed` (ADR-0012)
│   │   ├── venue_categories.py    # canonical slugs, language-independent
│   │   └── locales/
│   │       ├── __init__.py
│   │       ├── tr.py          # per-locale display names, one module per language
│   │       └── en.py          # (Phase 6)
│   ├── middleware/            # (Phase 7) rate limiting, request id, logging
│   │   └── __init__.py
│   └── main.py                # FastAPI app, lifespan, middleware registration
├── migrations/
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
├── docker/
│   └── postgres-init/         # runs once on container init (test DB, extensions)
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
│       └── conftest.py        # test-database session, rollback, query_counter
├── docs/
│   ├── project-structure.md
│   ├── roadmap.md
│   ├── testing-strategy.md
│   ├── local-setup.md         # (Phase 8)
│   └── deployment.md          # (Phase 8) written against the real Railway setup
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── justfile
├── pyproject.toml
├── uv.lock
├── Dockerfile                 # (Phase 8)
├── README.md
├── CHANGELOG.md
└── CLAUDE.md
```

## Notes on layout decisions

**One module per resource, across `models` / `schemas` / `services` /
`exceptions`.** A resource's model, its request/response schemas, its queries,
and its error types each live in the layer they belong to, named the same
thing — not bundled into one file per resource. The 300-line file limit in
[CLAUDE.md](../CLAUDE.md) applies here: a service that outgrows it is split by
concern, not allowed to keep growing.

**No repository layer.** Services hold their own queries. Revisit only if
services grow large and the same query starts being duplicated across several
of them.

**`app/middleware/` is separate from `app/core/`.** Everything in `core` is
imported and called explicitly by application code; middleware is registered
once against the app and runs on every request without a caller. Keeping the
two apart makes it obvious which is which.
