"""drop product layer, four venue criteria, user identity fields

Revision ID: 0c10d9ee531a
Revises: d13e2095d80e
Create Date: 2026-08-24 01:24:54.319699

Consolidates the schema onto ADR-0011 (product layer removed, venues rated on
four required criteria) and the account-lifecycle groundwork the PDD's §7
account-deletion semantics need.

Autogenerate produced the first draft of this, and three of its outputs were
wrong: it dropped `global_product_types` before the translation table that
references it, it added two `users` columns as `NOT NULL` with no default
against a table that already has rows, and it emitted `drop_constraint(None,
...)` in the downgrade, which has no name to drop. Adjusted by hand.

`rating_taste` is deliberately added as `NOT NULL` with no server default. If
this revision ever meets a database that already holds check-ins, it will
fail loudly rather than invent a rating — the four-point scale has no neutral
point (PDD §8), so there is no honest value to backfill with, and a fabricated
one would feed straight into a venue's aggregate. Clear such rows first, by
hand and deliberately.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c10d9ee531a"
down_revision: str | Sequence[str] | None = "d13e2095d80e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Frozen copies of `app.core.user_identity`'s constants as they stood at this
# revision. Deliberately duplicated rather than imported: a migration is a
# record of what happened here, and importing live application code couples
# frozen history to a moving target — see ADR-0012, and the guard in
# tests/unit/test_migration_isolation.py.
_USERNAME_NAMESPACE = uuid.UUID("3f2b1c4e-9d7a-5e18-8c06-2a4b6d0f9e33")
_USERNAME_FALLBACK_PREFIX = "user_"
_FALLBACK_SUFFIX_LENGTH = 12

_RATING_COLUMNS = ("rating_taste", "rating_service", "rating_ambiance", "rating_value")
_MIN_RATING = 1
_MAX_RATING = 4

_USER_STATUSES = ("active", "frozen", "suspended")
_DEFAULT_USER_STATUS = "active"

# Every user-owned row is purged with the account; a venue is a shared
# resource that outlives whoever added it and only loses the attribution.
_USER_CASCADE_FKS = (
    ("checkins", "user_id"),
    ("checkin_bookmarks", "user_id"),
    ("checkin_likes", "user_id"),
    ("follows", "follower_id"),
    ("follows", "following_id"),
    ("lists", "user_id"),
    ("list_bookmarks", "user_id"),
    ("list_likes", "user_id"),
    ("notifications", "user_id"),
    ("notifications", "actor_id"),
    ("venue_saves", "user_id"),
)
_VENUE_ADDED_BY_FK = ("venues", "added_by")


def _fk_name(table: str, column: str) -> str:
    """PostgreSQL's own naming convention for these constraints, which is
    what created them originally — reused so both directions of this
    migration name the same thing.
    """
    return f"{table}_{column}_fkey"


def _backfill_user_identity() -> None:
    """Give every existing user a handle and a display name before either
    column is made `NOT NULL`.

    Derived from the provider identity pair, exactly as
    `app.core.user_identity.fallback_username` does, so a row backfilled
    here and a row provisioned by the webhook resolve to the same handle.
    """
    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.UUID()),
        sa.column("auth_provider", sa.String()),
        sa.column("auth_provider_id", sa.String()),
        sa.column("username", sa.String()),
        sa.column("display_name", sa.String()),
    )

    rows = bind.execute(
        sa.select(users.c.id, users.c.auth_provider, users.c.auth_provider_id).where(
            users.c.username.is_(None)
        )
    ).all()

    for user_id, auth_provider, auth_provider_id in rows:
        derived = uuid.uuid5(
            _USERNAME_NAMESPACE, f"{auth_provider}:{auth_provider_id}"
        ).hex[:_FALLBACK_SUFFIX_LENGTH]
        bind.execute(
            users.update()
            .where(users.c.id == user_id)
            .values(username=f"{_USERNAME_FALLBACK_PREFIX}{derived}")
        )

    # Anyone who already had a handle (or just got one above) starts out
    # displaying it, matching `default_display_name`'s fallback when the
    # provider supplies no real name.
    bind.execute(
        users.update()
        .where(users.c.display_name.is_(None))
        .values(display_name=users.c.username)
    )


def upgrade() -> None:
    """Drop the product layer, move check-ins onto four required criteria,
    and give `USER` its identity/standing fields and delete policy.
    """
    # --- product layer: children before parents, or the foreign keys bite ---
    op.drop_index(op.f("ix_checkin_products_product_id"), table_name="checkin_products")
    op.drop_table("checkin_products")
    op.drop_index(op.f("ix_products_global_type_id"), table_name="products")
    op.drop_index(op.f("ix_products_venue_id"), table_name="products")
    op.drop_table("products")
    op.drop_table("global_product_type_translations")
    op.drop_index(
        op.f("ix_global_product_types_category_id"), table_name="global_product_types"
    )
    op.drop_table("global_product_types")

    # --- check-ins: four required criteria ---
    op.add_column("checkins", sa.Column("rating_taste", sa.Integer(), nullable=False))
    for column in ("rating_service", "rating_ambiance", "rating_value"):
        op.alter_column("checkins", column, existing_type=sa.INTEGER(), nullable=False)
        # The old constraints permitted NULL ("<col> IS NULL OR ..."), which
        # no longer matches the model. Left in place they would show as
        # permanent drift on every future autogenerate.
        op.drop_constraint(f"ck_checkins_{column}_range", "checkins", type_="check")
    for column in _RATING_COLUMNS:
        op.create_check_constraint(
            f"ck_checkins_{column}_range",
            "checkins",
            f"{column} BETWEEN {_MIN_RATING} AND {_MAX_RATING}",
        )

    # --- users: identity fields, added nullable and backfilled first ---
    op.add_column("users", sa.Column("display_name", sa.String(), nullable=True))
    _backfill_user_identity()
    op.alter_column("users", "display_name", existing_type=sa.String(), nullable=False)
    op.alter_column("users", "username", existing_type=sa.VARCHAR(), nullable=False)
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.add_column(
        "users",
        sa.Column(
            "status",
            sa.String(),
            server_default=_DEFAULT_USER_STATUS,
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_status_allowed",
        "users",
        "status IN (" + ", ".join(f"'{value}'" for value in _USER_STATUSES) + ")",
    )

    # --- delete policy on every reference to users.id ---
    for table, column in _USER_CASCADE_FKS:
        op.drop_constraint(_fk_name(table, column), table, type_="foreignkey")
        op.create_foreign_key(
            _fk_name(table, column),
            table,
            "users",
            [column],
            ["id"],
            ondelete="CASCADE",
        )

    table, column = _VENUE_ADDED_BY_FK
    op.alter_column("venues", column, existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(_fk_name(table, column), table, type_="foreignkey")
    op.create_foreign_key(
        _fk_name(table, column), table, "users", [column], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    """Restore the previous schema.

    Schema only: the rows in the four dropped tables are gone for good, and
    `rating_taste` values are discarded. A downgrade leaves a structurally
    valid database, not the one that existed before the upgrade.
    """
    table, column = _VENUE_ADDED_BY_FK
    op.drop_constraint(_fk_name(table, column), table, type_="foreignkey")
    op.create_foreign_key(_fk_name(table, column), table, "users", [column], ["id"])
    op.alter_column("venues", column, existing_type=sa.UUID(), nullable=False)

    for table, column in _USER_CASCADE_FKS:
        op.drop_constraint(_fk_name(table, column), table, type_="foreignkey")
        op.create_foreign_key(_fk_name(table, column), table, "users", [column], ["id"])

    op.drop_constraint("ck_users_status_allowed", "users", type_="check")
    op.drop_column("users", "status")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    op.alter_column("users", "username", existing_type=sa.VARCHAR(), nullable=True)
    op.drop_column("users", "display_name")

    for column in _RATING_COLUMNS:
        op.drop_constraint(f"ck_checkins_{column}_range", "checkins", type_="check")
    op.drop_column("checkins", "rating_taste")
    for column in ("rating_service", "rating_ambiance", "rating_value"):
        op.alter_column("checkins", column, existing_type=sa.INTEGER(), nullable=True)
        op.create_check_constraint(
            f"ck_checkins_{column}_range",
            "checkins",
            f"{column} IS NULL OR {column} BETWEEN {_MIN_RATING} AND {_MAX_RATING}",
        )

    # --- product layer: parents before children, mirroring the upgrade ---
    op.create_table(
        "global_product_types",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["venue_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        op.f("ix_global_product_types_category_id"),
        "global_product_types",
        ["category_id"],
        unique=False,
    )
    op.create_table(
        "global_product_type_translations",
        sa.Column("product_type_id", sa.UUID(), nullable=False),
        sa.Column("locale", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["product_type_id"], ["global_product_types.id"]),
        sa.PrimaryKeyConstraint("product_type_id", "locale"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("venue_id", sa.UUID(), nullable=False),
        sa.Column("global_type_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["global_type_id"], ["global_product_types.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_products_venue_id"), "products", ["venue_id"], unique=False
    )
    op.create_index(
        op.f("ix_products_global_type_id"), "products", ["global_type_id"], unique=False
    )
    op.create_table(
        "checkin_products",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("checkin_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            f"rating BETWEEN {_MIN_RATING} AND {_MAX_RATING}",
            name="ck_checkin_products_rating_range",
        ),
        sa.ForeignKeyConstraint(["checkin_id"], ["checkins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "checkin_id", "product_id", name="uq_checkin_products_checkin_product"
        ),
    )
    op.create_index(
        op.f("ix_checkin_products_product_id"),
        "checkin_products",
        ["product_id"],
        unique=False,
    )
