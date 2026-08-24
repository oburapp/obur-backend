"""enable RLS on users, follows, close_friends, notifications

Third RLS table group (ADR-0016 in obur-docs). All four are covered by
the functions the first two groups already created
(`rls_is_owner_or_admin`, `rls_is_admin`, `rls_current_user_id`), no new
helper functions needed here, but each table's policy still had to be
worked out on its own terms:

`users` is open on SELECT and INSERT, not owner-restricted. Two reasons,
not one: (1) there is no per-row secrecy concept for a user's own
identity row the way `visibility` gives checkins one, everyone already
sees everyone's basic profile; (2) restricting it would break identity
resolution itself, `app.core.auth._find_user` looks a user up by
`auth_provider_id` *before* any RLS identity is known, since that
lookup is what establishes it. UPDATE/DELETE are still owner-or-admin
(using the row's own `id` as the "owner" column, since a user owns
themselves), which works for `PATCH/DELETE /users/me` because
`get_current_user` has already set identity by the time those run. The
Clerk webhook is a different case, covered in `app/api/v1/webhooks.py`:
it never runs through `get_current_user` at all (no session token, a
Svix signature instead), so it now explicitly calls
`set_current_user_identity` for whichever user it already looked up
before writing to them, stating outright which already-verified
identity a system-triggered write is for.

`follows` and `close_friends` both needed a **cascade correctness**
check that isn't obvious from `can_view`/`ensure_visible_and_owned`
alone, found by tracing what account deletion actually cascades
through, not assumed: a `DELETE FROM users` purges that user's own
`follows` and `close_friends` rows directly, but it can *also* cascade
into another user's `close_friends` row, when the deleted account was
the *friend* being removed, since `close_friends`' composite FK depends
on the exact `follows` row the deletion just cascaded away. Whoever's
account is being deleted needs to be a valid actor for that delete even
when they aren't the row's primary owner column. Both tables' DELETE
policies therefore check *either* relevant column, not just one; this
is exactly why `follows` was already designed deletable by either party
(the PDD's own rule, not new here), and `close_friends` picks up the
same shape for the same underlying reason.

`notifications` has the one real INSERT wrinkle in this group: the
person triggering an event and the person the notification is *for* are
different (Ahmet likes Mehmet's check-in; the resulting notification
row has `user_id = Mehmet`, inserted while the acting identity is
Ahmet). An owner-matched INSERT check would block completely ordinary
notification creation, so INSERT only requires being authenticated at
all, the same shape `venues` already uses and for the same reason: the
real authorization decision (who should get notified about what) is
already made correctly in `app.services.notification` before this row
is ever inserted, RLS's INSERT check here is a much narrower "not
anonymous" backstop, not a re-derivation of that decision.

SELECT also has to allow the *actor*, not only the recipient, for a
reason that has nothing to do with privacy and everything to do with
`INSERT ... RETURNING`: every ORM flush uses it, to read back
server-generated defaults like `created_at`, and PostgreSQL requires
the just-inserted row to satisfy the table's SELECT policy for that,
not only the INSERT policy's WITH CHECK. An owner-only SELECT policy
made every notification insert fail the moment it went through the
real ORM path, found empirically: the identical INSERT succeeded
through plain `psql` without a RETURNING clause, and failed with the
same "violates row-level security policy" error the instant one was
added. UPDATE (marking read) stays owner-or-admin only, since nothing
about the actor needs write access there.

Revision ID: e4f8b21ac930
Revises: c1d5a8f042e7
Create Date: 2026-08-25 11:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4f8b21ac930"
down_revision: str | Sequence[str] | None = "c1d5a8f042e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY users_select ON users FOR SELECT USING (true)")
    op.execute("CREATE POLICY users_insert ON users FOR INSERT WITH CHECK (true)")
    op.execute(
        """
        CREATE POLICY users_update ON users
        FOR UPDATE
        USING (rls_is_owner_or_admin(id))
        WITH CHECK (rls_is_owner_or_admin(id))
        """
    )
    op.execute(
        "CREATE POLICY users_delete ON users "
        "FOR DELETE USING (rls_is_owner_or_admin(id))"
    )

    op.execute("ALTER TABLE follows ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY follows_select ON follows FOR SELECT USING (true)")
    op.execute(
        """
        CREATE POLICY follows_insert ON follows
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(follower_id))
        """
    )
    op.execute(
        """
        CREATE POLICY follows_delete ON follows
        FOR DELETE
        USING (
            rls_is_owner_or_admin(follower_id)
            OR rls_is_owner_or_admin(following_id)
        )
        """
    )

    op.execute("ALTER TABLE close_friends ENABLE ROW LEVEL SECURITY")
    # `OR rls_is_owner_or_admin(friend_id)`, not owner-only: found the
    # same way the notifications fix was found, by actually exercising
    # the real code path, not assumed. `app.core.authz.is_close_friend`
    # (called by `can_view` for every viewer of `close_friends`-tier
    # content) queries this table directly as whichever user is doing
    # the *viewing*, not the list owner, to answer "am I on this
    # person's close-friend list". An owner-only policy made that query
    # return nothing for anyone but the owner, which broke close-friends
    # visibility entirely for the one party who actually needs the
    # answer. This lets a specific friend confirm their own membership
    # (the row where `friend_id` matches them), it does not let them
    # list the owner's whole close-friends list, since every *other*
    # row still has a `user_id`/`friend_id` that isn't theirs.
    op.execute(
        """
        CREATE POLICY close_friends_select ON close_friends
        FOR SELECT
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin(friend_id)
        )
        """
    )
    op.execute(
        """
        CREATE POLICY close_friends_insert ON close_friends
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY close_friends_delete ON close_friends
        FOR DELETE
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin(friend_id)
        )
        """
    )

    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    # `OR rls_is_owner_or_admin(actor_id)`, not owner-only: PostgreSQL's
    # `INSERT ... RETURNING` (what every ORM flush issues, to read back
    # server-generated defaults like `created_at`) implicitly requires
    # the new row to also satisfy the table's SELECT policy, not just
    # the INSERT policy's WITH CHECK, found empirically (a bare `psql`
    # INSERT without RETURNING succeeded, the identical INSERT with
    # RETURNING raised the same "violates row-level security policy"
    # error). An owner-only SELECT policy would make every notification
    # insert fail the moment it's actually issued through the ORM,
    # since the actor (who triggers it) is essentially never the
    # recipient (who it's about). Letting the actor see a notification
    # their own action created is a reasonable rule on its own terms
    # too, not only a workaround for this.
    op.execute(
        """
        CREATE POLICY notifications_select ON notifications
        FOR SELECT
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin(actor_id)
        )
        """
    )
    op.execute(
        """
        CREATE POLICY notifications_insert ON notifications
        FOR INSERT
        WITH CHECK (rls_current_user_id() IS NOT NULL)
        """
    )
    op.execute(
        """
        CREATE POLICY notifications_update ON notifications
        FOR UPDATE
        USING (rls_is_owner_or_admin(user_id))
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY notifications_delete ON notifications
        FOR DELETE
        USING (rls_is_owner_or_admin(user_id))
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS notifications_delete ON notifications")
    op.execute("DROP POLICY IF EXISTS notifications_update ON notifications")
    op.execute("DROP POLICY IF EXISTS notifications_insert ON notifications")
    op.execute("DROP POLICY IF EXISTS notifications_select ON notifications")
    op.execute("ALTER TABLE notifications DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS close_friends_delete ON close_friends")
    op.execute("DROP POLICY IF EXISTS close_friends_insert ON close_friends")
    op.execute("DROP POLICY IF EXISTS close_friends_select ON close_friends")
    op.execute("ALTER TABLE close_friends DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS follows_delete ON follows")
    op.execute("DROP POLICY IF EXISTS follows_insert ON follows")
    op.execute("DROP POLICY IF EXISTS follows_select ON follows")
    op.execute("ALTER TABLE follows DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS users_delete ON users")
    op.execute("DROP POLICY IF EXISTS users_update ON users")
    op.execute("DROP POLICY IF EXISTS users_insert ON users")
    op.execute("DROP POLICY IF EXISTS users_select ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
