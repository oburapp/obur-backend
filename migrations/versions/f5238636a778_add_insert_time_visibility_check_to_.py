"""add insert-time visibility check to likes and bookmarks

`checkin_likes_insert`, `list_likes_insert`, `checkin_bookmarks_insert`,
and `list_bookmarks_insert` (migration f6a3d857e142) only ever checked
`rls_is_owner_or_admin(user_id)`, whoever's inserting is who they claim to
be, never whether they can actually see the checkin or list they're
attaching the row to. `app.services.like`/`app.services.bookmark` already
enforce that correctly (both resolve the target through `get_checkin`/
`get_list` first, which raises if it isn't visible), so no legitimate
flow was ever affected. The gap is a pure RLS-layer backstop missing, the
same class this project already treats as a real bug rather than a
theoretical one (see ADR-0016's Context in obur-docs, and CLAUDE.md's "RLS
is the layer that survives a query forgetting to call `can_view`").

Concretely: `INSERT ... RETURNING`, what every ORM flush issues, already
fails closed today, because the row just inserted must also satisfy the
table's SELECT policy (`checkin_likes_select` etc., resolving through
`rls_can_view_checkin`/`rls_can_view_list`), the exact same requirement
already documented in migration e4f8b21ac930 for `notifications`. But
that's an emergent property of the ORM's insert path issuing RETURNING by
default, not a rule this schema states, so a future bulk-insert helper
(CLAUDE.md explicitly allows a truncate-and-load or `ON CONFLICT`-based
bulk path for other tables) or a raw `INSERT` without `RETURNING` would
silently bypass it. This migration makes the rule explicit instead of
relying on that side effect, reusing the helper functions
`rls_can_view_checkin`/`rls_can_view_list` already created and granted to
`obur_app` in migration f6a3d857e142, no new function needed.

Unrelated to Phase 10 (blocking): found while designing that phase's own
RLS work and fixed on its own branch first, since it's a pre-existing gap
that would need the same fix even if Phase 10 didn't exist.

Revision ID: f5238636a778
Revises: f7514fe63beb
Create Date: 2026-08-25 16:01:37.792978

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5238636a778"
down_revision: str | Sequence[str] | None = "f7514fe63beb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER POLICY checkin_likes_insert ON checkin_likes
        WITH CHECK (
            rls_is_owner_or_admin(user_id)
            AND rls_can_view_checkin(checkin_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY list_likes_insert ON list_likes
        WITH CHECK (
            rls_is_owner_or_admin(user_id)
            AND rls_can_view_list(list_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY checkin_bookmarks_insert ON checkin_bookmarks
        WITH CHECK (
            rls_is_owner_or_admin(user_id)
            AND rls_can_view_checkin(checkin_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY list_bookmarks_insert ON list_bookmarks
        WITH CHECK (
            rls_is_owner_or_admin(user_id)
            AND rls_can_view_list(list_id)
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER POLICY list_bookmarks_insert ON list_bookmarks
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        ALTER POLICY checkin_bookmarks_insert ON checkin_bookmarks
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        ALTER POLICY list_likes_insert ON list_likes
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        ALTER POLICY checkin_likes_insert ON checkin_likes
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
