"""Fixtures specific to integration tests."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

_ALEMBIC_INI_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="session", autouse=True)
def _migrated_test_database() -> None:
    """Bring `obur_test`'s schema to head via the real Alembic migrations.

    Runs once per test session. Targets `obur_test` because the root
    conftest.py already points DATABASE_URL there before any `app.*`
    module — including `migrations/env.py`'s settings lookup — is
    imported. Idempotent: a database already at head is a no-op.
    """
    command.upgrade(Config(str(_ALEMBIC_INI_PATH)), "head")
