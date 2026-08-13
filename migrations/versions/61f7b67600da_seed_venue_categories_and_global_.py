"""seed venue categories and global product types

Revision ID: 61f7b67600da
Revises: 2052a9c7abfc
Create Date: 2026-08-13 19:05:04.512958

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.i18n import SUPPORTED_LOCALES
from app.seeds.global_product_types import GLOBAL_PRODUCT_TYPES
from app.seeds.identity import global_product_type_id, venue_category_id
from app.seeds.locales import get_global_product_type_names, get_venue_category_names
from app.seeds.venue_categories import VENUE_CATEGORIES

# revision identifiers, used by Alembic.
revision: str = "61f7b67600da"
down_revision: str | Sequence[str] | None = "2052a9c7abfc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

venue_categories = sa.table(
    "venue_categories",
    sa.column("id", sa.UUID()),
    sa.column("slug", sa.String()),
    sa.column("parent_id", sa.UUID()),
)
venue_category_translations = sa.table(
    "venue_category_translations",
    sa.column("category_id", sa.UUID()),
    sa.column("locale", sa.String()),
    sa.column("name", sa.String()),
)
global_product_types = sa.table(
    "global_product_types",
    sa.column("id", sa.UUID()),
    sa.column("slug", sa.String()),
    sa.column("category_id", sa.UUID()),
)
global_product_type_translations = sa.table(
    "global_product_type_translations",
    sa.column("product_type_id", sa.UUID()),
    sa.column("locale", sa.String()),
    sa.column("name", sa.String()),
)


def upgrade() -> None:
    """Bulk-upsert seed catalog rows, keyed by their stable slug."""
    bind = op.get_bind()

    category_rows = [
        {
            "id": venue_category_id(category.slug),
            "slug": category.slug,
            "parent_id": (
                venue_category_id(category.parent_slug)
                if category.parent_slug is not None
                else None
            ),
        }
        for category in VENUE_CATEGORIES
    ]
    upsert_categories = pg_insert(venue_categories).values(category_rows)
    upsert_categories = upsert_categories.on_conflict_do_update(
        index_elements=["slug"],
        set_={"parent_id": upsert_categories.excluded.parent_id},
    )
    bind.execute(upsert_categories)

    product_type_rows = [
        {
            "id": global_product_type_id(product_type.slug),
            "slug": product_type.slug,
            "category_id": venue_category_id(product_type.category_slug),
        }
        for product_type in GLOBAL_PRODUCT_TYPES
    ]
    upsert_product_types = pg_insert(global_product_types).values(product_type_rows)
    upsert_product_types = upsert_product_types.on_conflict_do_update(
        index_elements=["slug"],
        set_={"category_id": upsert_product_types.excluded.category_id},
    )
    bind.execute(upsert_product_types)

    for locale in SUPPORTED_LOCALES:
        category_names = get_venue_category_names(locale)
        category_translation_rows = [
            {
                "category_id": venue_category_id(category.slug),
                "locale": locale,
                "name": category_names[category.slug],
            }
            for category in VENUE_CATEGORIES
        ]
        upsert_category_translations = pg_insert(venue_category_translations).values(
            category_translation_rows
        )
        upsert_category_translations = (
            upsert_category_translations.on_conflict_do_update(
                index_elements=["category_id", "locale"],
                set_={"name": upsert_category_translations.excluded.name},
            )
        )
        bind.execute(upsert_category_translations)

        product_type_names = get_global_product_type_names(locale)
        product_type_translation_rows = [
            {
                "product_type_id": global_product_type_id(product_type.slug),
                "locale": locale,
                "name": product_type_names[product_type.slug],
            }
            for product_type in GLOBAL_PRODUCT_TYPES
        ]
        upsert_product_type_translations = pg_insert(
            global_product_type_translations
        ).values(product_type_translation_rows)
        upsert_product_type_translations = (
            upsert_product_type_translations.on_conflict_do_update(
                index_elements=["product_type_id", "locale"],
                set_={"name": upsert_product_type_translations.excluded.name},
            )
        )
        bind.execute(upsert_product_type_translations)


def downgrade() -> None:
    """Remove seeded rows, children before parents to satisfy foreign keys."""
    bind = op.get_bind()

    product_type_ids = [
        global_product_type_id(product_type.slug)
        for product_type in GLOBAL_PRODUCT_TYPES
    ]
    bind.execute(
        global_product_type_translations.delete().where(
            global_product_type_translations.c.product_type_id.in_(product_type_ids)
        )
    )
    bind.execute(
        global_product_types.delete().where(
            global_product_types.c.id.in_(product_type_ids)
        )
    )

    category_ids = [venue_category_id(category.slug) for category in VENUE_CATEGORIES]
    bind.execute(
        venue_category_translations.delete().where(
            venue_category_translations.c.category_id.in_(category_ids)
        )
    )
    # Delete leaf-first (reverse of VENUE_CATEGORIES' parent-before-child
    # order) so a category is never removed while a child still points at
    # it via the self-referential `parent_id` foreign key.
    for category in reversed(VENUE_CATEGORIES):
        bind.execute(
            venue_categories.delete().where(
                venue_categories.c.id == venue_category_id(category.slug)
            )
        )
