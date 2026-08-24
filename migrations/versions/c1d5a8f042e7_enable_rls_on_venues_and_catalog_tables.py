"""enable RLS on venues and catalog tables

Second RLS table group (ADR-0016 in obur-docs), grouped by access
pattern the same way the first group was: `venues`, `venue_categories`,
and `venue_category_translations` are all fully public, shared reference
data with no per-row visibility concept at all, the opposite pattern
from checkins/lists/venue_saves. Nobody's `visibility` column decides
whether these rows can be seen; everybody sees all of them.

`venue_categories` / `venue_category_translations` get a SELECT policy
and *no* mutation policy at all. That is deliberate, not an oversight:
with RLS enabled and no policy for a command, the default is deny, so
the app role literally cannot write to the catalog tables once this
lands, matching what's already true in practice (ADR-0012: reference
data is seeded, never written by the running app) but not, until now,
enforced by anything beyond convention.

`venues` does get a real mutation policy, since venue creation is a
normal, currently-shipped user action (`POST /api/v1/venues`), but
`added_by` is nullable and can be `NULL` (ADR-0011: a venue outlives the
account that added it) or literally anyone's id at creation time in
principle, so there is no "owner must match" rule to enforce the way
checkins/lists/venue_saves have one. The only real backstop available
today is authentication: an anonymous connection (no identity ever set)
cannot insert a venue. There is currently no venue update/delete
endpoint at all (Phase 9's "no venue field is user-editable" already
describes where this is headed), so both are admin-only here, ahead of
that phase landing, rather than left open to a surface nothing serves
yet.

Revision ID: c1d5a8f042e7
Revises: b7e4f209ac31
Create Date: 2026-08-25 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d5a8f042e7"
down_revision: str | Sequence[str] | None = "b7e4f209ac31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_TABLES: tuple[str, ...] = (
    "venue_categories",
    "venue_category_translations",
)

_APP_ROLE_NAME = "obur_app"

# A standalone admin check, not `rls_is_owner_or_admin(NULL)`: that would
# also work (`NULL = rls_current_user_id()` is never true, so it reduces
# to just the admin branch), but relies on the reader knowing SQL's
# three-valued NULL logic to see why. A named function says what it
# means.
_CREATE_IS_ADMIN_FUNCTION_SQL = """
CREATE FUNCTION rls_is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM users WHERE id = rls_current_user_id() AND role = 'admin'
    );
$$;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(_CREATE_IS_ADMIN_FUNCTION_SQL)
    op.execute(f"GRANT EXECUTE ON FUNCTION rls_is_admin() TO {_APP_ROLE_NAME}")

    for table in _CATALOG_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_select ON {table} FOR SELECT USING (true)")

    op.execute("ALTER TABLE venues ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY venues_select ON venues FOR SELECT USING (true)")
    op.execute(
        """
        CREATE POLICY venues_insert ON venues
        FOR INSERT
        WITH CHECK (rls_current_user_id() IS NOT NULL)
        """
    )
    op.execute(
        """
        CREATE POLICY venues_update ON venues
        FOR UPDATE
        USING (rls_is_admin())
        WITH CHECK (rls_is_admin())
        """
    )
    op.execute(
        """
        CREATE POLICY venues_delete ON venues
        FOR DELETE
        USING (rls_is_admin())
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS venues_delete ON venues")
    op.execute("DROP POLICY IF EXISTS venues_update ON venues")
    op.execute("DROP POLICY IF EXISTS venues_insert ON venues")
    op.execute("DROP POLICY IF EXISTS venues_select ON venues")
    op.execute("ALTER TABLE venues DISABLE ROW LEVEL SECURITY")

    for table in _CATALOG_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_select ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS rls_is_admin()")
