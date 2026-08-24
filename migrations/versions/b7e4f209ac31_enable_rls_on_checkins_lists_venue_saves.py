"""enable RLS on checkins, lists, venue_saves

First table group to get Row Level Security, per ADR-0016 in obur-docs:
`CHECKIN`, `LIST`, and `VENUE_SAVE` share one visibility model already
(three tiers, `app.core.visibility.Visibility`; see `app/models/checkin.py`'s
module docstring), and one authorization function
(`app.core.authz.can_view`) already implements it in Python. This
migration re-expresses that same rule in SQL, as four small helper
functions the policies below call, so there is exactly one SQL
implementation to compare against the Python one, not one copy of the
logic per table.

`SECURITY DEFINER` on the helper functions is deliberate, not a stray
privilege escalation: without it, `rls_is_owner_or_admin`'s own lookup
against `users` (to check `role = 'admin'`) would itself be subject to
`users`' own RLS policy once that table gets one, which risks a policy
needing a policy to evaluate. Defining these functions with the owning
(table-owner) role's privileges, the same way a table owner already
bypasses RLS, breaks that potential circularity. The functions are
narrow, parameterized, and only ever return a boolean, they don't expose
arbitrary data.

Only `checkins`, `lists`, and `venue_saves` here. The remaining tables
(bookmarks, likes, notifications, close_friends, follows, users, venues,
the catalog tables) each have a different access pattern and are
deliberately left for a following migration rather than mechanically
reusing this one, per the roadmap's own standing rule: deciding a query's
access pattern is cheaper to get right once, while it's being written,
than to re-audit later.

Revision ID: b7e4f209ac31
Revises: f3a8c1d92b47
Create Date: 2026-08-24 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4f209ac31"
down_revision: str | Sequence[str] | None = "f3a8c1d92b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE_NAME = "obur_app"

# The three tables sharing the owner + three-tier-visibility pattern.
# Every one of them has a `user_id` (owner) column and a `visibility`
# column using the same allowed values, enforced by each table's own
# `ck_<table>_visibility_allowed` CHECK constraint.
_VISIBILITY_TABLES: tuple[str, ...] = ("checkins", "lists", "venue_saves")

# asyncpg's prepared-statement protocol refuses a string containing more
# than one SQL command (`cannot insert multiple commands into a prepared
# statement`), unlike psycopg2's simple query protocol, found by actually
# running this migration, not assumed. Each statement is therefore its own
# `op.execute()` call, one function per tuple entry below, rather than one
# big multi-statement string.
_CREATE_HELPER_FUNCTIONS_SQL: tuple[str, ...] = (
    # `NULLIF(..., '')`, not a bare cast: on a pooled connection, a custom
    # (never-declared-in-postgresql.conf) GUC that a prior, since-rolled-
    # back transaction touched with SET LOCAL settles back to an empty
    # string rather than truly unset, found empirically, not assumed.
    # `current_setting(..., true)` alone therefore isn't reliably NULL
    # for "no identity", and a bare `::uuid` cast on `''` raises rather
    # than failing closed. Every other function here goes through this
    # one instead of reading the setting directly, so the fix (and any
    # future one like it) lives in exactly one place.
    """
    CREATE FUNCTION rls_current_user_id()
    RETURNS uuid
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid;
    $$;
    """,
    """
    CREATE FUNCTION rls_is_owner_or_admin(check_owner_id uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT
            check_owner_id = rls_current_user_id()
            OR EXISTS (
                SELECT 1 FROM users
                WHERE id = rls_current_user_id()
                AND role = 'admin'
            );
    $$;
    """,
    """
    CREATE FUNCTION rls_is_close_friend_of(check_owner_id uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT EXISTS (
            SELECT 1 FROM close_friends
            WHERE user_id = check_owner_id
            AND friend_id = rls_current_user_id()
        );
    $$;
    """,
    # Mirrors app.core.authz.can_view exactly: owner or admin always sees
    # it, then public/private/close_friends in that order. A visibility
    # value outside the three known ones (shouldn't happen, the CHECK
    # constraint already enforces this) falls through to "not visible",
    # the same fail-closed default can_view's own final `return False` has.
    """
    CREATE FUNCTION rls_can_view_visibility(check_owner_id uuid, check_visibility text)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT
            rls_is_owner_or_admin(check_owner_id)
            OR check_visibility = 'public'
            OR (
                check_visibility = 'close_friends'
                AND rls_is_close_friend_of(check_owner_id)
            );
    $$;
    """,
)

# Dependents first, `rls_current_user_id` last: the other three are
# defined in terms of it, so dropping it first would fail.
_DROP_HELPER_FUNCTIONS_SQL: tuple[str, ...] = (
    "DROP FUNCTION IF EXISTS rls_can_view_visibility(uuid, text)",
    "DROP FUNCTION IF EXISTS rls_is_close_friend_of(uuid)",
    "DROP FUNCTION IF EXISTS rls_is_owner_or_admin(uuid)",
    "DROP FUNCTION IF EXISTS rls_current_user_id()",
)


def upgrade() -> None:
    """Upgrade schema."""
    for statement in _CREATE_HELPER_FUNCTIONS_SQL:
        op.execute(statement)
    op.execute(f"GRANT EXECUTE ON FUNCTION rls_current_user_id() TO {_APP_ROLE_NAME}")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION rls_is_owner_or_admin(uuid) TO {_APP_ROLE_NAME}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION rls_is_close_friend_of(uuid) TO {_APP_ROLE_NAME}"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION rls_can_view_visibility(uuid, text) TO "
        f"{_APP_ROLE_NAME}"
    )

    for table in _VISIBILITY_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # SELECT mirrors can_view in full: owner/admin, public, or a
        # qualifying close friend.
        op.execute(
            f"""
            CREATE POLICY {table}_select ON {table}
            FOR SELECT
            USING (rls_can_view_visibility(user_id, visibility))
            """
        )
        # Mutation is stricter than visibility on purpose, matching
        # app.core.authz.ensure_visible_and_owned: being able to *see* a
        # public row (anyone) is not being able to *change* it (owner or
        # admin only). Three separate policies, not one `FOR ALL`,
        # because `FOR ALL` would apply this stricter rule to SELECT too
        # and break public readability.
        op.execute(
            f"""
            CREATE POLICY {table}_insert ON {table}
            FOR INSERT
            WITH CHECK (rls_is_owner_or_admin(user_id))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_update ON {table}
            FOR UPDATE
            USING (rls_is_owner_or_admin(user_id))
            WITH CHECK (rls_is_owner_or_admin(user_id))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_delete ON {table}
            FOR DELETE
            USING (rls_is_owner_or_admin(user_id))
            """
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in _VISIBILITY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_delete ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_update ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_insert ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_select ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for statement in _DROP_HELPER_FUNCTIONS_SQL:
        op.execute(statement)
