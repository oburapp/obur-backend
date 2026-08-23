"""seed venue categories and global product types

Revision ID: 61f7b67600da
Revises: 2052a9c7abfc
Create Date: 2026-08-13 19:05:04.512958

Superseded — this migration is now intentionally a no-op.

As originally written it imported `VENUE_CATEGORIES`, `GLOBAL_PRODUCT_TYPES`,
`SUPPORTED_LOCALES`, and the seed identity/locale helpers from `app/`, then
bulk-upserted the catalog rows. That coupled a frozen historical record to
mutable application code, and it broke exactly the way Django's own
documentation warns it will: the migration "may work initially but will fail
in the future when you try to rerun old migrations (commonly, when you set up
a new installation and run through all the migrations to set up the
database)". Here it failed the moment the product-layer seed module was
removed (ADR-0011), taking the whole Alembic environment with it.

Catalog data is reference data, not history: it describes what the catalog
should contain *now*, and it is expected to grow. It therefore belongs to an
idempotent seeder that runs on every deploy, not to a one-shot migration —
see ADR-0012 in obur-docs, and `app/seeds/runner.py` for the seeder that owns
it now. Databases that already ran this migration keep their rows; the seeder
upserts the same slugs, so re-running it changes nothing.

The revision is kept (rather than deleted) so the revision chain stays
intact for any database that has already recorded it as applied.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "61f7b67600da"
down_revision: str | Sequence[str] | None = "2052a9c7abfc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: catalog seeding moved to the seeder (ADR-0012)."""


def downgrade() -> None:
    """No-op: this revision no longer writes anything to undo."""
