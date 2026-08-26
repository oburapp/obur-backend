"""add blocking mute and reporting tables

Schema from ADR-0010 in obur-docs (`blocks`, `content_reports`,
`venue_reports`) and PDD §7 (`mutes`, decided earlier, no ADR needed).
Behaviour from PDD §11.

`blocks`' own access control is deliberately stricter than every other
directional relationship table (`follows`, `close_friends`, `mutes`):
`blocks_select` is blocker-only, so the blocked person's own session can
never successfully `SELECT` a block naming them, under any circumstance.
Every enforcement check therefore goes through the new
`rls_is_blocked_pair` function, a `SECURITY DEFINER` bypass in the same
shape as `rls_is_admin()` (migration c1d5a8f042e7), rather than a plain
correlated subquery the way `close_friends`' membership check works. See
ADR-0010's "access control" section for the full reasoning and the two
alternatives considered.

`mutes` has no equivalent problem and needs no bypass function: nothing
ever checks a mute from the *muted* person's session (PDD §11, mute only
ever filters the *muter's* own feed), so a plain muter-only policy is
enough, `SELECT` and `DELETE` alike.

Both `blocks_delete` and `mutes_delete` are single-column (blocker-only,
muter-only), not permissive on the other party the way `follows_delete`/
`close_friends_delete` are. That asymmetry is deliberate, not an
oversight: those two tables let *either* party end the relationship
through the application, a real product rule (PDD §11's Social Graph),
so their policies need to allow both. Blocking and muting don't, "only
the blocker may unblock" is explicit in PDD §11, and nothing else ever
deletes a mute. `DELETE FROM users` cascading into either table via `ON
DELETE CASCADE` never consults these policies at all regardless of how
they're written: PostgreSQL's referential integrity checks always
bypass row security ("Row Security Policies" in the PostgreSQL manual),
specifically so a policy can never leave a dangling foreign key behind.
A wider policy here would therefore buy nothing for cascade correctness
while genuinely weakening the one rule that matters: it would let the
blocked (or muted) person delete the row protecting the other party
from them, through any future code path that issues a raw `DELETE`.

Blocking enforcement extends into RLS on every table it has to reach,
not only `app.core.authz.can_view` (`docs/roadmap.md`'s Phase 10 entry,
corrected alongside ADR-0010):

- `rls_can_view_visibility` (migration b7e4f209ac31) gains a blocking
  guard around its `public`/`close_friends` branches, which propagates
  to `checkins_select`, `lists_select`, `venue_saves_select`, and
  (transitively, through `rls_can_view_checkin`/`rls_can_view_list`)
  `checkin_likes_select`, `list_likes_select`, and `list_items_select`,
  six policies corrected by one function edit.
- `users_select` (migration e4f8b21ac930, currently `USING (true)`)
  gains the same guard, so a blocked profile behaves like a nonexistent
  one to the other party (PDD §11), without reopening the
  identity-resolution problem that keeps it from being owner-restricted:
  nobody is ever blocked relative to themselves.
- `notifications_select`/`notifications_insert` (migration e4f8b21ac930)
  both gain the guard, admin exempted on `_select` only (admin
  moderation access is never affected by a block, PDD §11); this is a
  forward-looking backstop, the retroactive purge of existing
  cross-block notifications is service-layer work, not this migration's.

`content_reports`/`venue_reports` get no blocking guard at all and no
`DELETE` policy: reports are a permanent moderation record an admin must
always be able to review "regardless of who blocked whom" (PDD §11), the
same "no policy for a command means deny" choice `venue_categories`
already made (migration c1d5a8f042e7) for the same "should never be
written to outside its one sanctioned path" reason.

Both report tables also carry an optional `details` free-text column,
required only when `reason` is `other` (a correlated `CHECK`, one per
table). `ContentReportReason.SEXUAL_CONTENT` is renamed to
`SENSITIVE_CONTENT` (`sensitive_content`) in the same pass, a broader
label than the category it replaces.

Revision ID: 190c719287e2
Revises: 222227e6de3b
Create Date: 2026-08-25 16:20:27.369416

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "190c719287e2"
down_revision: str | Sequence[str] | None = "222227e6de3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE_NAME = "obur_app"

_CREATE_RLS_IS_BLOCKED_PAIR_SQL = """
CREATE FUNCTION rls_is_blocked_pair(user_a uuid, user_b uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM blocks
        WHERE (blocker_id = user_a AND blocked_id = user_b)
           OR (blocker_id = user_b AND blocked_id = user_a)
    );
$$;
"""

_NEW_CAN_VIEW_VISIBILITY_SQL = """
CREATE OR REPLACE FUNCTION rls_can_view_visibility(
    check_owner_id uuid, check_visibility text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT
        rls_is_owner_or_admin(check_owner_id)
        OR (
            NOT rls_is_blocked_pair(check_owner_id, rls_current_user_id())
            AND (
                check_visibility = 'public'
                OR (
                    check_visibility = 'close_friends'
                    AND rls_is_close_friend_of(check_owner_id)
                )
            )
        );
$$;
"""

_OLD_CAN_VIEW_VISIBILITY_SQL = """
CREATE OR REPLACE FUNCTION rls_can_view_visibility(
    check_owner_id uuid, check_visibility text
)
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
"""


def upgrade() -> None:
    """Upgrade schema."""
    # --- new tables (autogenerated from app/models/, hand-reviewed) ---
    op.create_table(
        "blocks",
        sa.Column("blocker_id", sa.UUID(), nullable=False),
        sa.Column("blocked_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("blocker_id != blocked_id", name="ck_blocks_no_self_block"),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
    )
    op.create_index(
        op.f("ix_blocks_blocked_id"), "blocks", ["blocked_id"], unique=False
    )

    op.create_table(
        "mutes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("muted_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("user_id != muted_id", name="ck_mutes_no_self_mute"),
        sa.ForeignKeyConstraint(["muted_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "muted_id"),
    )

    op.create_table(
        "content_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=True),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ("
            "'spam', 'harassment', 'hate_speech', 'sensitive_content', "
            "'violence', 'fake_account', 'other'"
            ")",
            name="ck_content_reports_reason_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'dismissed', 'actioned')",
            name="ck_content_reports_status_allowed",
        ),
        sa.CheckConstraint(
            "target_type IN ('checkin', 'user')",
            name="ck_content_reports_target_type_allowed",
        ),
        sa.CheckConstraint(
            "reason != 'other' OR (details IS NOT NULL AND details != '')",
            name="ck_content_reports_details_required_for_other",
        ),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporter_id",
            "target_type",
            "target_id",
            name="uq_content_reports_reporter_target",
        ),
    )
    op.create_index(
        op.f("ix_content_reports_reporter_id"),
        "content_reports",
        ["reporter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_reports_target_id"),
        "content_reports",
        ["target_id"],
        unique=False,
    )

    op.create_table(
        "venue_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=True),
        sa.Column("venue_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ("
            "'wrong_address', 'wrong_name', 'permanently_closed', "
            "'duplicate', 'other'"
            ")",
            name="ck_venue_reports_reason_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'dismissed', 'actioned')",
            name="ck_venue_reports_status_allowed",
        ),
        sa.CheckConstraint(
            "reason != 'other' OR (details IS NOT NULL AND details != '')",
            name="ck_venue_reports_details_required_for_other",
        ),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reporter_id", "venue_id", name="uq_venue_reports_reporter_venue"
        ),
    )
    op.create_index(
        op.f("ix_venue_reports_reporter_id"),
        "venue_reports",
        ["reporter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_venue_reports_venue_id"), "venue_reports", ["venue_id"], unique=False
    )

    # --- rls_is_blocked_pair: must exist before anything below uses it ---
    op.execute(_CREATE_RLS_IS_BLOCKED_PAIR_SQL)
    op.execute(
        f"GRANT EXECUTE ON FUNCTION rls_is_blocked_pair(uuid, uuid) TO {_APP_ROLE_NAME}"
    )

    # --- blocks: blocker-only SELECT (Option B, ADR-0010) ---
    op.execute("ALTER TABLE blocks ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY blocks_select ON blocks
        FOR SELECT
        USING (rls_is_owner_or_admin(blocker_id))
        """
    )
    op.execute(
        """
        CREATE POLICY blocks_insert ON blocks
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(blocker_id))
        """
    )
    # Blocker-only, matching "only the blocker may unblock" exactly (PDD
    # §11, ADR-0010) with no gap: PostgreSQL's referential integrity
    # checks always bypass row security ("Row Security Policies" in the
    # manual), so DELETE FROM users cascading into this table via ON
    # DELETE CASCADE never consults this policy at all, for either
    # party. Nothing about account-deletion cascade correctness needs
    # this policy to be any wider than the actual product rule.
    op.execute(
        """
        CREATE POLICY blocks_delete ON blocks
        FOR DELETE
        USING (rls_is_owner_or_admin(blocker_id))
        """
    )

    # --- mutes: muter-only, no bypass function needed (see docstring) ---
    op.execute("ALTER TABLE mutes ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY mutes_select ON mutes
        FOR SELECT
        USING (rls_is_owner_or_admin(user_id))
        """
    )
    op.execute(
        """
        CREATE POLICY mutes_insert ON mutes
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(user_id))
        """
    )
    # Muter-only, for the same reason blocks_delete is blocker-only: the
    # muted person has no legitimate action here at all (PDD §11), and
    # account-deletion cascades never consult this policy (see the note
    # on blocks_delete above).
    op.execute(
        """
        CREATE POLICY mutes_delete ON mutes
        FOR DELETE
        USING (rls_is_owner_or_admin(user_id))
        """
    )

    # --- content_reports: reporter-or-admin read, reporter-only write,
    # admin-only resolve, no delete (a permanent moderation record) ---
    op.execute("ALTER TABLE content_reports ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY content_reports_select ON content_reports
        FOR SELECT
        USING (rls_is_owner_or_admin(reporter_id))
        """
    )
    op.execute(
        """
        CREATE POLICY content_reports_insert ON content_reports
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(reporter_id))
        """
    )
    op.execute(
        """
        CREATE POLICY content_reports_update ON content_reports
        FOR UPDATE
        USING (rls_is_admin())
        WITH CHECK (rls_is_admin())
        """
    )

    # --- venue_reports: same shape as content_reports ---
    op.execute("ALTER TABLE venue_reports ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY venue_reports_select ON venue_reports
        FOR SELECT
        USING (rls_is_owner_or_admin(reporter_id))
        """
    )
    op.execute(
        """
        CREATE POLICY venue_reports_insert ON venue_reports
        FOR INSERT
        WITH CHECK (rls_is_owner_or_admin(reporter_id))
        """
    )
    op.execute(
        """
        CREATE POLICY venue_reports_update ON venue_reports
        FOR UPDATE
        USING (rls_is_admin())
        WITH CHECK (rls_is_admin())
        """
    )

    # --- blocking enforcement on already-existing tables ---
    op.execute(_NEW_CAN_VIEW_VISIBILITY_SQL)
    op.execute(
        """
        ALTER POLICY users_select ON users
        USING (rls_is_admin() OR NOT rls_is_blocked_pair(id, rls_current_user_id()))
        """
    )
    op.execute(
        """
        ALTER POLICY notifications_select ON notifications
        USING (
            (rls_is_owner_or_admin(user_id) OR rls_is_owner_or_admin(actor_id))
            AND (rls_is_admin() OR NOT rls_is_blocked_pair(user_id, actor_id))
        )
        """
    )
    op.execute(
        """
        ALTER POLICY notifications_insert ON notifications
        WITH CHECK (
            rls_current_user_id() IS NOT NULL
            AND NOT rls_is_blocked_pair(user_id, actor_id)
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        ALTER POLICY notifications_insert ON notifications
        WITH CHECK (rls_current_user_id() IS NOT NULL)
        """
    )
    op.execute(
        """
        ALTER POLICY notifications_select ON notifications
        USING (
            rls_is_owner_or_admin(user_id)
            OR rls_is_owner_or_admin(actor_id)
        )
        """
    )
    op.execute(
        """
        ALTER POLICY users_select ON users
        USING (true)
        """
    )
    op.execute(_OLD_CAN_VIEW_VISIBILITY_SQL)

    op.execute("DROP POLICY IF EXISTS venue_reports_update ON venue_reports")
    op.execute("DROP POLICY IF EXISTS venue_reports_insert ON venue_reports")
    op.execute("DROP POLICY IF EXISTS venue_reports_select ON venue_reports")
    op.execute("ALTER TABLE venue_reports DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS content_reports_update ON content_reports")
    op.execute("DROP POLICY IF EXISTS content_reports_insert ON content_reports")
    op.execute("DROP POLICY IF EXISTS content_reports_select ON content_reports")
    op.execute("ALTER TABLE content_reports DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS mutes_delete ON mutes")
    op.execute("DROP POLICY IF EXISTS mutes_insert ON mutes")
    op.execute("DROP POLICY IF EXISTS mutes_select ON mutes")
    op.execute("ALTER TABLE mutes DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS blocks_delete ON blocks")
    op.execute("DROP POLICY IF EXISTS blocks_insert ON blocks")
    op.execute("DROP POLICY IF EXISTS blocks_select ON blocks")
    op.execute("ALTER TABLE blocks DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS rls_is_blocked_pair(uuid, uuid)")

    op.drop_index(op.f("ix_venue_reports_venue_id"), table_name="venue_reports")
    op.drop_index(op.f("ix_venue_reports_reporter_id"), table_name="venue_reports")
    op.drop_table("venue_reports")

    op.drop_index(op.f("ix_content_reports_target_id"), table_name="content_reports")
    op.drop_index(op.f("ix_content_reports_reporter_id"), table_name="content_reports")
    op.drop_table("content_reports")

    op.drop_table("mutes")

    op.drop_index(op.f("ix_blocks_blocked_id"), table_name="blocks")
    op.drop_table("blocks")
