# Project Structure

Target directory layout for `obur-backend`. This is a planning reference —
once the structure exists in code, the actual filesystem is the source of
truth, not this file. Update this file when the top-level layout changes.

```
obur-backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── checkins.py
│   │       ├── venues.py
│   │       ├── users.py
│   │       ├── products.py
│   │       ├── lists.py
│   │       └── badges.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py          # settings via pydantic-settings
│   │   ├── database.py        # async engine, session factory
│   │   ├── redis.py           # redis client
│   │   └── security.py        # clerk JWT verification
│   ├── models/
│   │   ├── __init__.py        # re-exports Base + all model classes
│   │   ├── base.py            # shared SQLAlchemy declarative base
│   │   └── user.py            # one module per resource (added as built)
│   ├── schemas/
│   │   └── __init__.py        # Pydantic request/response schemas, one module per resource
│   ├── services/
│   │   └── __init__.py        # business logic, DB queries, one module per resource
│   ├── exceptions/
│   │   └── __init__.py        # custom exceptions, one module per service domain
│   ├── middleware/
│   │   └── __init__.py        # rate limiting, logging, auth
│   └── main.py                # FastAPI app, lifespan, middleware registration
├── migrations/
│   ├── versions/
│   └── env.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── docs/
│   ├── local-setup.md
│   ├── deployment.md
│   ├── testing-strategy.md
│   ├── roadmap.md
│   └── project-structure.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
└── CHANGELOG.md
```
