"""enable RLS on likes, bookmarks, list_items

Fourth and final RLS table group for this pass (ADR-0016 in obur-docs):
`checkin_likes`, `list_likes`, `checkin_bookmarks`, `list_bookmarks`, and
`list_items`. All five share a pattern none of the earlier groups had,
visibility and, for `list_items`, even ownership itself, is *derived
from a parent row* (the checkin or list being liked/bookmarked/
contained), not from a column on the table's own row. `list_items` has
no owner column at all; a list item is owned by whoever owns the list.

Four new helper functions, mirroring the shape of the first group's
`rls_can_view_visibility`/`rls_is_owner_or_admin` but resolving *through*
a foreign key first:

- `rls_can_view_checkin(uuid)` / `rls_can_view_list(uuid)`: is the
  current caller allowed to see the referenced checkin/list at all
  (owner, admin, public, or a qualifying close friend). Used for SELECT
  on the derived tables. A referenced row that no longer exists resolves
  to `NULL`, which `USING` treats as not-visible, the same fail-closed
  default every other policy here already has.
- `rls_is_owner_or_admin_of_checkin(uuid)` / `rls_is_owner_or_admin_of_list(uuid)`:
  narrower, is the current caller specifically the *owner* (or admin) of
  the referenced checkin/list. This is not redundant with the pair
  above; it's needed for two different reasons depending on the table:
  `list_items`' own mutation rights (it has no owner column of its own),
  and a cascade-correctness case bookmarks/likes both have that
  `close_friends`/`follows` already needed a version of (see migration
  e4f8b21ac930): deleting a *checkin owner's* account cascades away
  other users' likes/bookmarks on that owner's content too, and the
  identity active at that point is the deleted owner, not the liker or
  bookmarker.

Two things checked before writing any policy below, not assumed, because
both broke earlier groups in this same pass: whether the inserter can
also satisfy the SELECT policy for the row they just inserted
(`INSERT ... RETURNING` requires it, see migration e4f8b21ac930's
`notifications` fix), and whether a DELETE policy needs to account for
*both* sides of a relationship for cascade correctness, not just the
row's most obvious "owner" column.

`checkin_likes` / `list_likes`: a semi-public signal (PDD §6, "liking
something requires being able to see it first"). SELECT therefore
checks the referenced content's visibility, not the like row's own
`user_id`. INSERT/DELETE stay owner-matched (you like/unlike as
yourself), except DELETE also allows the referenced checkin/list's own
owner-or-admin, for the cascade case above.

`checkin_bookmarks` / `list_bookmarks`: always private to the
bookmarker, "nobody, including the checkin's owner, can see who
bookmarked it" (see app/models/checkin_bookmark.py). SELECT is
therefore owner-only, deliberately *not* derived from the referenced
content's visibility the way likes are. INSERT/DELETE mirror likes:
owner-matched, with the same cascade allowance on DELETE.

`list_items` has no visibility or ownership of its own at all; every
policy here defers entirely to the parent list.

Revision ID: f6a3d857e142
Revises: e4f8b21ac930
Create Date: 2026-08-25 13:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a3d857e142"
down_revision: str | Sequence[str] | None = "e4f8b21ac930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE_NAME = "obur_app"

_CREATE_HELPER_FUNCTIONS_SQL: tuple[str, ...] = (
    """
    CREATE FUNCTION rls_can_view_checkin(check_checkin_id uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT rls_can_view_visibility(checkins.user_id, checkins.visibility)
        FROM checkins WHERE checkins.id = check_checkin_id;
    $$;
    """,
    """
    CREATE FUNCTION rls_can_view_list(check_list_id uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT rls_can_view_visibility(lists.user_id, lists.visibility)
        FROM lists WHERE lists.id = check_list_id;
    $$;
    """,
    """
    CREATE FUNCTION rls_is_owner_or_admin_of_checkin(check_checkin_id uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT rls_is_owner_or_admin(checkins.user_id)
        FROM checkins WHERE checkins.id = check_checkin_id;
    $$;
    """,
    """
    CREATE FUNCTION rls_is_owner_or_admin_of_list(check_list_id uuid)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SECURITY DEFINER
    SET search_path = public
    AS $$
        SELECT rls_is_owner_or_admin(lists.user_id)
        FROM lists WHERE lists.id = check_list_id;
    $$;
    """,
)

_HELPER_FUNCTION_SIGNATURES: tuple[str, ...] = (
    "rls_can_view_checkin(uuid)",
    "rls_can_view_list(uuid)",
    "rls_is_owner_or_admin_of_checkin(uuid)",
    "rls_is_owner_or_admin_of_list(uuid)",
)


def upgrade() -> None:
    """Upgrade schema."""
    for statement in _CREATE_HELPER_FUNCTIONS_SQL:
        op.execute(statement)
    for signature in _HELPER_FUNCTION_SIGNATURES:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {_APP_ROLE_NAME}")

    # checkin_likes
    op.execute("ALTER TABLE checkin_likes ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY checkin_likes_select ON checkin_likes
        FOR SELECT
        USING (rls_can_view_checkin(checkin_id))
        """
    )
    op.execute(
        """
        CREATE POLICY checkin_likes_insert ON checkin_likes
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY checkin_likes_delete ON checkin_likes
        FOR DELETE
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_checkin(checkin_id)
        )
        """
    )

    # list_likes
    op.execute("ALTER TABLE list_likes ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY list_likes_select ON list_likes
        FOR SELECT
        USING (rls_can_view_list(list_id))
        """
    )
    op.execute(
        """
        CREATE POLICY list_likes_insert ON list_likes
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY list_likes_delete ON list_likes
        FOR DELETE
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_list(list_id)
        )
        """
    )

    # checkin_bookmarks
    op.execute("ALTER TABLE checkin_bookmarks ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY checkin_bookmarks_select ON checkin_bookmarks
        FOR SELECT
        USING (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY checkin_bookmarks_insert ON checkin_bookmarks
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY checkin_bookmarks_delete ON checkin_bookmarks
        FOR DELETE
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_checkin(checkin_id)
        )
        """
    )

    # list_bookmarks
    op.execute("ALTER TABLE list_bookmarks ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY list_bookmarks_select ON list_bookmarks
        FOR SELECT
        USING (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY list_bookmarks_insert ON list_bookmarks
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY list_bookmarks_delete ON list_bookmarks
        FOR DELETE
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_list(list_id)
        )
        """
    )

    # list_items: no column of its own to check, every policy defers to
    # the parent list.
    op.execute("ALTER TABLE list_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY list_items_select ON list_items
        FOR SELECT
        USING (rls_can_view_list(list_id))
        """
    )
    op.execute(
        """
        CREATE POLICY list_items_insert ON list_items
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin_of_list(list_id))
        """
    )
    op.execute(
        """
        CREATE POLICY list_items_update ON list_items
        FOR UPDATE
        USING (rls_is_owner_or_admin_of_list(list_id))
        WITH CHECK (rls_is_owner_or_admin_of_list(list_id))
        """
    )
    op.execute(
        """
        CREATE POLICY list_items_delete ON list_items
        FOR DELETE
        USING (rls_is_owner_or_admin_of_list(list_id))
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS list_items_delete ON list_items")
    op.execute("DROP POLICY IF EXISTS list_items_update ON list_items")
    op.execute("DROP POLICY IF EXISTS list_items_insert ON list_items")
    op.execute("DROP POLICY IF EXISTS list_items_select ON list_items")
    op.execute("ALTER TABLE list_items DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS list_bookmarks_delete ON list_bookmarks")
    op.execute("DROP POLICY IF EXISTS list_bookmarks_insert ON list_bookmarks")
    op.execute("DROP POLICY IF EXISTS list_bookmarks_select ON list_bookmarks")
    op.execute("ALTER TABLE list_bookmarks DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS checkin_bookmarks_delete ON checkin_bookmarks")
    op.execute("DROP POLICY IF EXISTS checkin_bookmarks_insert ON checkin_bookmarks")
    op.execute("DROP POLICY IF EXISTS checkin_bookmarks_select ON checkin_bookmarks")
    op.execute("ALTER TABLE checkin_bookmarks DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS list_likes_delete ON list_likes")
    op.execute("DROP POLICY IF EXISTS list_likes_insert ON list_likes")
    op.execute("DROP POLICY IF EXISTS list_likes_select ON list_likes")
    op.execute("ALTER TABLE list_likes DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS checkin_likes_delete ON checkin_likes")
    op.execute("DROP POLICY IF EXISTS checkin_likes_insert ON checkin_likes")
    op.execute("DROP POLICY IF EXISTS checkin_likes_select ON checkin_likes")
    op.execute("ALTER TABLE checkin_likes DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS rls_is_owner_or_admin_of_list(uuid)")
    op.execute("DROP FUNCTION IF EXISTS rls_is_owner_or_admin_of_checkin(uuid)")
    op.execute("DROP FUNCTION IF EXISTS rls_can_view_list(uuid)")
    op.execute("DROP FUNCTION IF EXISTS rls_can_view_checkin(uuid)")
