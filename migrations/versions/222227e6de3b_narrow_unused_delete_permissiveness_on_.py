"""narrow unused delete permissiveness on close friends likes and bookmarks

`close_friends_delete`, `checkin_likes_delete`, `list_likes_delete`,
`checkin_bookmarks_delete`, and `list_bookmarks_delete` (migrations
e4f8b21ac930, f6a3d857e142) were all written permissive on a second
column, on the reasoning that account-deletion cascades needed it:
"DELETE FROM users for either party cascades into this table, and the
identity active during that cascade is whichever account is being
deleted." That reasoning is factually wrong, found and corrected while
building Phase 10's own `blocks`/`mutes` policies (see the
`add_blocking_mute_and_reporting_tables` migration and ADR-0010):
PostgreSQL's referential integrity checks always bypass row security
("Row Security Policies" in the PostgreSQL manual), so none of these
five policies were ever actually needed for cascade correctness.

Once that reasoning is set aside, each policy has to justify its second
branch on its own actual merits, checked against the real application,
not assumed:

- `follows_delete` (not touched by this migration) keeps its second
  branch, `rls_is_owner_or_admin(following_id)`: `DELETE
  /api/v1/users/me/followers/{follower_id}` (app/api/v1/follows.py) is
  a real, shipped feature, "the followed user removing that follower
  from their own followers list" (PDD §11).
- The five narrowed here have no equivalent. Nothing in
  `app/services/close_friend.py` lets `friend_id` remove themselves,
  there is no such endpoint in `app/api/v1/close_friends.py` and PDD
  §11 never describes one. Nothing in `app/services/like.py` or
  `app/services/bookmark.py` lets a checkin's or list's owner remove
  someone else's like or bookmark, `unlike_checkin`/`unlike_list`/
  `unbookmark_checkin`/`unbookmark_list` all resolve strictly against
  `current_user`'s own row, and `app/api/v1/admin.py` has no
  like/bookmark moderation endpoint either.

None of the five was reachable through any shipped code path, so this
migration changes no observable behavior, existing tests keep passing
unmodified. What it removes is a standing gap between what the database
would allow and what the application ever does: exactly the case Row
Level Security exists to close, per `obur-backend/CLAUDE.md`'s own
"survives a query forgetting to call it" framing, just found here on
the DELETE side instead of the read side that framing was written for.

Revision ID: 222227e6de3b
Revises: f5238636a778
Create Date: 2026-08-25 18:18:56.598446

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "222227e6de3b"
down_revision: str | Sequence[str] | None = "f5238636a778"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        ALTER POLICY close_friends_delete ON close_friends
        USING (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        ALTER POLICY checkin_likes_delete ON checkin_likes
        USING (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        ALTER POLICY list_likes_delete ON list_likes
        USING (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        ALTER POLICY checkin_bookmarks_delete ON checkin_bookmarks
        USING (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        ALTER POLICY list_bookmarks_delete ON list_bookmarks
        USING (rls_is_owner_or_admin(user_id))
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER POLICY list_bookmarks_delete ON list_bookmarks
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_list(list_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY checkin_bookmarks_delete ON checkin_bookmarks
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_checkin(checkin_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY list_likes_delete ON list_likes
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_list(list_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY checkin_likes_delete ON checkin_likes
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin_of_checkin(checkin_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY close_friends_delete ON close_friends
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin(friend_id)
        )
        """
    )
