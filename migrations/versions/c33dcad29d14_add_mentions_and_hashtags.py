"""add mentions and hashtags

ADR-0019 in obur-docs.

`hashtags` is a shared catalog keyed on the case-insensitive match key;
`checkin_hashtags` / `list_hashtags` link it to the text that carries it;
`checkin_mentions` records who a check-in's note mentions. All three link
tables are derived from text by the application on every create and edit.

RLS: `hashtags` is readable by everyone and insertable by any
authenticated user, never updated or deleted by the application. The link
tables and `checkin_mentions` follow their parent check-in or list: readable
when it is (`rls_can_view_checkin` / `rls_can_view_list`), written only by
its owner or an admin (`rls_is_owner_or_admin_of_checkin` / `_of_list`).

`rls_purge_interactions_between` (migration 619903be1de5) gains mentions,
so a block removes them in both directions alongside likes, bookmarks, and
notifications.

`rls_purge_close_friend_mentions` is an `AFTER DELETE` trigger on
`close_friends`. A person mentioned in a `close_friends` check-in can see it
only while they're on the author's close friends list, and that row
disappears three ways: the author removes them, they unfollow, or the
author removes them as a follower. The last two are foreign-key cascades
from `follows` that application code never sees, so the guarantee lives in
the database, a named exception to the no-raw-SQL rule like RLS policy DDL
(see CLAUDE.md). `SECURITY DEFINER` because the deleting session may be the
friend's, who has no right to delete rows on the author's check-ins.

Revision ID: c33dcad29d14
Revises: aecd8f51cd44
Create Date: 2026-11-13 02:42:32.948588

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

_OWNER_OF_CHECKIN = "rls_is_owner_or_admin_of_checkin(checkin_id)"
_OWNER_OF_LIST = "rls_is_owner_or_admin_of_list(list_id)"

# (table, SELECT condition, write condition)
_DERIVED_TABLES = (
    ("checkin_hashtags", "rls_can_view_checkin(checkin_id)", _OWNER_OF_CHECKIN),
    ("list_hashtags", "rls_can_view_list(list_id)", _OWNER_OF_LIST),
    ("checkin_mentions", "rls_can_view_checkin(checkin_id)", _OWNER_OF_CHECKIN),
)

_PURGE_WITH_MENTIONS_SQL = """
CREATE OR REPLACE FUNCTION rls_purge_interactions_between(user_a uuid, user_b uuid)
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

    DELETE FROM checkin_mentions
    WHERE (mentioned_user_id = user_a AND checkin_id IN (
               SELECT id FROM checkins WHERE user_id = user_b
           ))
       OR (mentioned_user_id = user_b AND checkin_id IN (
               SELECT id FROM checkins WHERE user_id = user_a
           ));

    DELETE FROM notifications
    WHERE (user_id = user_a AND actor_id = user_b)
       OR (user_id = user_b AND actor_id = user_a);
END;
$$;
"""

# The definition migration 619903be1de5 created, restored on downgrade.
_PURGE_WITHOUT_MENTIONS_SQL = """
CREATE OR REPLACE FUNCTION rls_purge_interactions_between(user_a uuid, user_b uuid)
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

_CREATE_CLOSE_FRIEND_TRIGGER_FUNCTION_SQL = """
CREATE FUNCTION rls_purge_close_friend_mentions()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    DELETE FROM checkin_mentions
    WHERE mentioned_user_id = OLD.friend_id
      AND checkin_id IN (
          SELECT id FROM checkins
          WHERE user_id = OLD.user_id AND visibility = 'close_friends'
      );
    RETURN OLD;
END;
$$;
"""

_CREATE_CLOSE_FRIEND_TRIGGER_SQL = """
CREATE TRIGGER trg_close_friends_purge_mentions
AFTER DELETE ON close_friends
FOR EACH ROW EXECUTE FUNCTION rls_purge_close_friend_mentions()
"""

# revision identifiers, used by Alembic.
revision: str = "c33dcad29d14"
down_revision: str | Sequence[str] | None = "aecd8f51cd44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "hashtags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tag"),
    )
    op.create_table(
        "list_hashtags",
        sa.Column("list_id", sa.UUID(), nullable=False),
        sa.Column("hashtag_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["hashtag_id"], ["hashtags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["list_id"], ["lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("list_id", "hashtag_id"),
    )
    op.create_index(
        op.f("ix_list_hashtags_hashtag_id"),
        "list_hashtags",
        ["hashtag_id"],
        unique=False,
    )
    op.create_table(
        "checkin_hashtags",
        sa.Column("checkin_id", sa.UUID(), nullable=False),
        sa.Column("hashtag_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["checkin_id"], ["checkins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hashtag_id"], ["hashtags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("checkin_id", "hashtag_id"),
    )
    op.create_index(
        op.f("ix_checkin_hashtags_hashtag_id"),
        "checkin_hashtags",
        ["hashtag_id"],
        unique=False,
    )
    op.create_table(
        "checkin_mentions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("checkin_id", sa.UUID(), nullable=False),
        sa.Column("mentioned_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["checkin_id"], ["checkins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mentioned_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "checkin_id",
            "mentioned_user_id",
            name="uq_checkin_mentions_checkin_id_mentioned_user_id",
        ),
    )
    op.create_index(
        op.f("ix_checkin_mentions_checkin_id"),
        "checkin_mentions",
        ["checkin_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_checkin_mentions_mentioned_user_id"),
        "checkin_mentions",
        ["mentioned_user_id"],
        unique=False,
    )
    # ### end Alembic commands ###
    _enable_rls()
    op.execute(_PURGE_WITH_MENTIONS_SQL)
    op.execute(_CREATE_CLOSE_FRIEND_TRIGGER_FUNCTION_SQL)
    op.execute(_CREATE_CLOSE_FRIEND_TRIGGER_SQL)


def _enable_rls() -> None:
    op.execute("ALTER TABLE hashtags ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY hashtags_select ON hashtags FOR SELECT USING (true)")
    op.execute(
        "CREATE POLICY hashtags_insert ON hashtags "
        "FOR INSERT WITH CHECK (rls_current_user_id() IS NOT NULL)"
    )
    for table, can_read, can_write in _DERIVED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_select ON {table} FOR SELECT USING ({can_read})"
        )
        op.execute(
            f"CREATE POLICY {table}_insert ON {table} "
            f"FOR INSERT WITH CHECK ({can_write})"
        )
        op.execute(
            f"CREATE POLICY {table}_delete ON {table} FOR DELETE USING ({can_write})"
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_close_friends_purge_mentions ON close_friends"
    )
    op.execute("DROP FUNCTION IF EXISTS rls_purge_close_friend_mentions()")
    op.execute(_PURGE_WITHOUT_MENTIONS_SQL)
    # Dropping the tables below drops their policies with them.
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        op.f("ix_checkin_mentions_mentioned_user_id"), table_name="checkin_mentions"
    )
    op.drop_index(op.f("ix_checkin_mentions_checkin_id"), table_name="checkin_mentions")
    op.drop_table("checkin_mentions")
    op.drop_index(op.f("ix_checkin_hashtags_hashtag_id"), table_name="checkin_hashtags")
    op.drop_table("checkin_hashtags")
    op.drop_index(op.f("ix_list_hashtags_hashtag_id"), table_name="list_hashtags")
    op.drop_table("list_hashtags")
    op.drop_table("hashtags")
    # ### end Alembic commands ###
