"""add block retroactive purge function

PDD §11: "Existing likes, bookmarks, and notifications between the two
people are purged in both directions at the moment of blocking." Follows
need no bypass, `follows_delete` is already permissive on both columns
for a real, shipped feature (`DELETE /users/me/followers/{id}`), so the
blocking service can clear them with two ordinary `unfollow_user` calls,
which cascades `close_friends` away for free via its existing FK.

Likes, bookmarks, and notifications are different: since migration
222227e6de3b, `checkin_likes_delete`/`list_likes_delete`/
`checkin_bookmarks_delete`/`list_bookmarks_delete` are owner-only, and
`notifications_delete` (migration e4f8b21ac930) only ever authorized the
recipient, never the actor. Both are correct for the ordinary case, a
content owner has no business deleting someone else's like, an actor has
no business deleting a notification that isn't theirs, but blocking is
the one case where removing exactly that needs to happen: the other
party's like on my content, or a notification naming both of us
regardless of which one of us is the recipient.

`rls_purge_interactions_between` is a narrow `SECURITY DEFINER` bypass
for that one operation, the same shape as `rls_verify_venue_if_eligible`
(migration f7514fe63beb): owned by the table-owning role, so it can
write past the ordinary policies above, granted `EXECUTE` to `obur_app`
so the blocking service can call it, and it does exactly this one thing,
nothing else. It doesn't touch `blocks` itself and doesn't verify a
block actually exists between the two ids, that's the caller's job
(`app.services.block.create_block`, calling this immediately after
inserting the block row): the function's only responsibility is the
mechanical purge, not re-deriving why it's being asked to run.

Revision ID: 619903be1de5
Revises: 190c719287e2
Create Date: 2026-08-26 15:17:15.717400

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "619903be1de5"
down_revision: str | Sequence[str] | None = "190c719287e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE_NAME = "obur_app"

_CREATE_PURGE_FUNCTION_SQL = """
CREATE FUNCTION rls_purge_interactions_between(user_a uuid, user_b uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    DELETE FROM checkin_likes
    WHERE (user_id = user_a AND checkin_id IN (
               SELECT id FROM checkins WHERE user_id = user_b
           ))
       OR (user_id = user_b AND checkin_id IN (
               SELECT id FROM checkins WHERE user_id = user_a
           ));

    DELETE FROM list_likes
    WHERE (user_id = user_a AND list_id IN (
               SELECT id FROM lists WHERE user_id = user_b
           ))
       OR (user_id = user_b AND list_id IN (
               SELECT id FROM lists WHERE user_id = user_a
           ));

    DELETE FROM checkin_bookmarks
    WHERE (user_id = user_a AND checkin_id IN (
               SELECT id FROM checkins WHERE user_id = user_b
           ))
       OR (user_id = user_b AND checkin_id IN (
               SELECT id FROM checkins WHERE user_id = user_a
           ));

    DELETE FROM list_bookmarks
    WHERE (user_id = user_a AND list_id IN (
               SELECT id FROM lists WHERE user_id = user_b
           ))
       OR (user_id = user_b AND list_id IN (
               SELECT id FROM lists WHERE user_id = user_a
           ));

    DELETE FROM notifications
    WHERE (user_id = user_a AND actor_id = user_b)
       OR (user_id = user_b AND actor_id = user_a);
END;
$$;
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(_CREATE_PURGE_FUNCTION_SQL)
    op.execute(
        "GRANT EXECUTE ON FUNCTION rls_purge_interactions_between(uuid, uuid) "
        f"TO {_APP_ROLE_NAME}"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION IF EXISTS rls_purge_interactions_between(uuid, uuid)")
