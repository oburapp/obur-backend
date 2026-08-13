"""replace turkish fts search_vector with trigram name search

See obur-docs ADR-0003 for the full rationale: a single Turkish-only
`tsvector` doesn't serve venue names in arbitrary languages, doesn't
tolerate typos, and doesn't match partial input. `pg_trgm` word-similarity
search on `name` covers all of those; `unaccent` (via an `IMMUTABLE`
wrapper, since `unaccent()` itself is `STABLE` and can't be indexed
directly) folds diacritics so e.g. "doner" matches "Döner".

Revision ID: ed402e8663f4
Revises: 61f7b67600da
Create Date: 2026-08-13 20:01:47.456476

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ed402e8663f4"
down_revision: str | Sequence[str] | None = "61f7b67600da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_UNACCENT_SQL = """
CREATE OR REPLACE FUNCTION immutable_unaccent(text)
RETURNS text AS
$$
  SELECT unaccent('unaccent', $1)
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(_IMMUTABLE_UNACCENT_SQL)

    op.drop_column("venues", "search_vector")

    op.execute(
        "CREATE INDEX idx_venues_name_trgm ON venues "
        "USING gin (immutable_unaccent(name) gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS idx_venues_name_trgm")

    op.add_column(
        "venues",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('turkish', name)", persisted=True),
            nullable=False,
        ),
    )

    # `immutable_unaccent` and the pg_trgm/unaccent extensions are left in
    # place rather than dropped — harmless to leave installed, and other
    # objects created independently of this migration could depend on
    # them by the time a downgrade runs.
