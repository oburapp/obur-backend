"""add a narrow blocklist-only bypass for the blockers own list

Found while building `app.services.block.list_blocked_users`:
`users_select`'s blocking guard (migration 190c719287e2) is fully
symmetric, neither party can see the other's row, which correctly
means a blocker managing their own blocklist can't see who's on it
either (username, avatar, for an unblock button, the same information
any real app's blocked-accounts screen shows).

An earlier version of this migration "fixed" that by widening
`users_select` itself with an `rls_am_i_blocking` exception. That was
wrong, caught before it ever reached `main`: `users_select` governs
every query that touches `users`, not just the blocklist screen, so
the widened policy let the blocker resolve the blocked person's
profile anywhere their id surfaced, a third party's checkin's likes, a
shared follower list, anywhere `users` gets joined, not only the one
screen that actually needs it. `users_select` stays exactly as
migration 190c719287e2 left it.

`rls_list_blocked_users` is the narrow replacement: a table-returning
`SECURITY DEFINER` function scoped to this one query, joining `blocks`
to `users` directly rather than going through `users_select` at all.
Nothing else gains access to the blocked person's row through it, the
same "narrow, purpose-built, does exactly one thing" shape as
`rls_verify_venue_if_eligible` and `rls_purge_interactions_between`.

Takes no `blocker_id` parameter, deliberately: it reads
`rls_current_user_id()` internally instead, the same way `rls_is_admin()`
never takes a caller-supplied id either. A `SECURITY DEFINER` function
is a real RLS bypass, so trusting an external parameter for whose
blocklist to return would only be as safe as every future caller
happening to pass their own id, exactly the class of mistake this
function exists to make impossible rather than merely unlikely.

Revision ID: f1d017015e34
Revises: 619903be1de5
Create Date: 2026-08-26 15:31:23.802132

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1d017015e34"
down_revision: str | Sequence[str] | None = "619903be1de5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE_NAME = "obur_app"

_CREATE_LIST_BLOCKED_USERS_SQL = """
CREATE FUNCTION rls_list_blocked_users(p_limit int, p_offset int)
RETURNS SETOF users
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT u.*
    FROM users u
    JOIN blocks b ON b.blocked_id = u.id
    WHERE b.blocker_id = rls_current_user_id()
    ORDER BY b.created_at DESC
    LIMIT p_limit OFFSET p_offset;
$$;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(_CREATE_LIST_BLOCKED_USERS_SQL)
    op.execute(
        "GRANT EXECUTE ON FUNCTION rls_list_blocked_users(int, int) "
        f"TO {_APP_ROLE_NAME}"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION IF EXISTS rls_list_blocked_users(int, int)")
