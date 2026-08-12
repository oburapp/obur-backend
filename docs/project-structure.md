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
│   │   └── __init__.py        # SQLAlchemy ORM models
│   ├── schemas/
│   │   └── __init__.py        # Pydantic request/response schemas
│   ├── services/
│   │   └── __init__.py        # business logic, DB queries
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
│   └── project-structure.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.yml
└── CHANGELOG.md
```
