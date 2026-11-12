"""add checkin drafts and checkin idempotency key

ADR-0018 in obur-docs.

`checkin_drafts`: a server-synced, in-progress check-in, a separate table
so a draft can never leak into an aggregate, badge, or feed query.

`checkins.idempotency_key` / `idempotency_payload_hash`: a retried
submission resolves to the original row. Existing rows are backfilled
before the columns become NOT NULL, so the database itself guarantees
every check-in has a key and no code path can create one that skips the
duplicate guard. A backfilled key is a random UUID no client holds, so no
request will ever match it; its hash is a placeholder derived from the
row id for the same reason, it is never compared against anything.

RLS on `checkin_drafts` is owner-only for every operation, with **no
admin exception**, a deliberate departure from the
`rls_is_owner_or_admin` pattern every other owned table uses (ADR-0016).
A draft is unpublished content: it can't be reported, never appears in a
feed, needs no moderation, and may hold notes the user never meant to
share. Account deletion still removes drafts, via the `ON DELETE CASCADE`
on `user_id`; referential cascades never consult RLS policies.

Autogenerate also proposed dropping `uq_venues_google_places_id`. That
index is created by migration f7514fe63beb and is not declared on the
model, so autogenerate misreads it as stale. It is deliberately left
alone here.

Revision ID: aecd8f51cd44
Revises: f1d017015e34
Create Date: 2026-11-12 22:04:27.519289

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aecd8f51cd44"
down_revision: str | Sequence[str] | None = "f1d017015e34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literal values, not imported from app/ (ADR-0012).
_MIN_RATING = 1
_MAX_RATING = 4
_DEFAULT_VISIBILITY = "public"
_ALLOWED_VISIBILITIES = ("public", "close_friends", "private")
_RATING_COLUMNS = ("rating_taste", "rating_service", "rating_ambiance", "rating_value")
_PAYLOAD_HASH_LENGTH = 64
_IDEMPOTENCY_UNIQUE = "uq_checkins_user_id_idempotency_key"

_OWNER_ONLY = "user_id = rls_current_user_id()"

_checkins = sa.table(
    "checkins",
    sa.column("id", sa.UUID()),
    sa.column("idempotency_key", sa.UUID()),
    sa.column("idempotency_payload_hash", sa.String()),
)


def _create_checkin_drafts() -> None:
    allowed = ", ".join(f"'{value}'" for value in _ALLOWED_VISIBILITIES)
    op.create_table(
        "checkin_drafts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("venue_id", sa.UUID(), nullable=True),
        *(sa.Column(column, sa.Integer(), nullable=True) for column in _RATING_COLUMNS),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("photo_url", sa.String(), nullable=True),
        sa.Column(
            "visibility",
            sa.String(),
            server_default=_DEFAULT_VISIBILITY,
            nullable=False,
        ),
        sa.Column("visited_at", sa.Date(), nullable=True),
        sa.Column("visited_tz", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"visibility IN ({allowed})", name="ck_checkin_drafts_visibility_allowed"
        ),
        sa.CheckConstraint(
            "(visited_at IS NULL) = (visited_tz IS NULL)",
            name="ck_checkin_drafts_visited_at_tz_paired",
        ),
        *(
            sa.CheckConstraint(
                f"{column} BETWEEN {_MIN_RATING} AND {_MAX_RATING}",
                name=f"ck_checkin_drafts_{column}_range",
            )
            for column in _RATING_COLUMNS
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_checkin_drafts_user_id_updated_at",
        "checkin_drafts",
        ["user_id", "updated_at"],
    )
    op.create_index("ix_checkin_drafts_venue_id", "checkin_drafts", ["venue_id"])


def _enable_checkin_drafts_rls() -> None:
    op.execute("ALTER TABLE checkin_drafts ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY checkin_drafts_select ON checkin_drafts "
        f"FOR SELECT USING ({_OWNER_ONLY})"
    )
    op.execute(
        f"CREATE POLICY checkin_drafts_insert ON checkin_drafts "
        f"FOR INSERT WITH CHECK ({_OWNER_ONLY})"
    )
    op.execute(
        f"CREATE POLICY checkin_drafts_update ON checkin_drafts "
        f"FOR UPDATE USING ({_OWNER_ONLY}) WITH CHECK ({_OWNER_ONLY})"
    )
    op.execute(
        f"CREATE POLICY checkin_drafts_delete ON checkin_drafts "
        f"FOR DELETE USING ({_OWNER_ONLY})"
    )


def _add_checkin_idempotency() -> None:
    op.add_column("checkins", sa.Column("idempotency_key", sa.UUID(), nullable=True))
    op.add_column(
        "checkins",
        sa.Column(
            "idempotency_payload_hash",
            sa.String(length=_PAYLOAD_HASH_LENGTH),
            nullable=True,
        ),
    )
    row_id_digest = sa.func.encode(
        sa.func.sha256(sa.func.convert_to(sa.cast(_checkins.c.id, sa.Text), "UTF8")),
        "hex",
    )
    op.execute(
        _checkins.update().values(
            idempotency_key=sa.func.gen_random_uuid(),
            idempotency_payload_hash=row_id_digest,
        )
    )
    op.alter_column("checkins", "idempotency_key", nullable=False)
    op.alter_column("checkins", "idempotency_payload_hash", nullable=False)
    op.create_unique_constraint(
        _IDEMPOTENCY_UNIQUE, "checkins", ["user_id", "idempotency_key"]
    )


def upgrade() -> None:
    """Upgrade schema."""
    _create_checkin_drafts()
    _enable_checkin_drafts_rls()
    _add_checkin_idempotency()


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_IDEMPOTENCY_UNIQUE, "checkins", type_="unique")
    op.drop_column("checkins", "idempotency_payload_hash")
    op.drop_column("checkins", "idempotency_key")
    # Dropping the table drops its policies with it.
    op.drop_index("ix_checkin_drafts_venue_id", table_name="checkin_drafts")
    op.drop_index("ix_checkin_drafts_user_id_updated_at", table_name="checkin_drafts")
    op.drop_table("checkin_drafts")
