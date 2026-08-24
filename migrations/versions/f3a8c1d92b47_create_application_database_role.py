"""create application database role

Creates the least-privilege `obur_app` role the running API connects as
from Phase 8 onward, per ADR-0016 in obur-docs (Database Roles and Row
Level Security). This migration only creates the role and grants the
baseline table access every read/write path needs. Row Level Security
itself (ENABLE ROW LEVEL SECURITY, CREATE POLICY) lands in a later
migration, once each table's policy has been designed on its own terms
rather than mechanically repeated across all of them.

The role's password is read from the `APP_DB_ROLE_PASSWORD` environment
variable directly via `os.environ`, not `app.core.config.Settings`:
migrations never import from `app/` (see CLAUDE.md), so this is the one
place in the codebase that reads this specific variable raw.
`load_dotenv()` is a safe no-op in any environment where the variable is
already exported into the process (Railway's deploy environment); it
only matters locally, where `.env` isn't loaded into the process by
default the way `app.core.config.Settings` loads it.

Revision ID: f3a8c1d92b47
Revises: a29f4e0a038b
Create Date: 2026-08-24 09:00:00.000000

"""

import os
from collections.abc import Sequence

from alembic import op
from dotenv import load_dotenv

# revision identifiers, used by Alembic.
revision: str = "f3a8c1d92b47"
down_revision: str | Sequence[str] | None = "a29f4e0a038b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE_NAME = "obur_app"


def _app_role_password() -> str:
    """Read the app role's password from the environment, escaped for
    safe interpolation into a DDL string (`CREATE ROLE` does not accept
    bind parameters, the same PostgreSQL protocol limitation already hit
    and documented in `app/services/venue.py` for `SET LOCAL`).

    Doubling embedded single quotes is the standard SQL string-literal
    escape; this value is operator-controlled configuration, never user
    input, the same trust boundary already accepted for
    `MIN_NAME_SIMILARITY` in that same file.
    """
    load_dotenv()
    return os.environ["APP_DB_ROLE_PASSWORD"].replace("'", "''")


def upgrade() -> None:
    """Upgrade schema."""
    password = _app_role_password()
    # Roles live at the Postgres *cluster* level, not inside one database,
    # unlike tables: a role created while migrating one database is already
    # there when migrating another in the same cluster. Locally, `obur` and
    # `obur_test` are two databases in the same cluster (see
    # docker/postgres-init), and both run this same migration independently,
    # so a plain `CREATE ROLE` would fail the second time with "role already
    # exists". Guarded the same way `CREATE TABLE IF NOT EXISTS` would be,
    # just without the shorthand Postgres doesn't offer for `CREATE ROLE`.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{_APP_ROLE_NAME}'
            ) THEN
                EXECUTE format(
                    'CREATE ROLE %I LOGIN PASSWORD %L '
                    'NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS INHERIT',
                    '{_APP_ROLE_NAME}',
                    '{password}'
                );
            END IF;
        END $$;
        """
    )
    # PostgreSQL's `GRANT ... ON DATABASE` clause takes a literal
    # identifier, not an expression, so `current_database()` has to be
    # resolved inside a dynamic `EXECUTE` rather than passed directly.
    # Doing it this way (instead of hardcoding the database name) means
    # this migration behaves identically in local dev (`obur`) and on
    # Railway (whatever the provisioned database happens to be named).
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format(
                'GRANT CONNECT ON DATABASE %I TO %I',
                current_database(),
                '{_APP_ROLE_NAME}'
            );
        END $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE_NAME}")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        f"TO {_APP_ROLE_NAME}"
    )
    # Every table a *future* migration adds is created by the role that
    # runs migrations, so without this, each one would need its own
    # explicit grant to obur_app, easy to forget, and the cost of
    # forgetting is an endpoint that fails on a permission error the day
    # that table ships, not at review time.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE_NAME}"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_APP_ROLE_NAME}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE_NAME}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE_NAME}")
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format(
                'REVOKE CONNECT ON DATABASE %I FROM %I',
                current_database(),
                '{_APP_ROLE_NAME}'
            );
        END $$;
        """
    )
    # Guarded for the same reason `CREATE ROLE` is guarded in `upgrade()`:
    # in a shared local cluster, `obur` and `obur_test` both run this
    # downgrade independently, and whichever runs second would otherwise
    # fail against a role the first one already dropped.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT FROM pg_roles WHERE rolname = '{_APP_ROLE_NAME}'
            ) THEN
                EXECUTE format('DROP ROLE %I', '{_APP_ROLE_NAME}');
            END IF;
        END $$;
        """
    )
