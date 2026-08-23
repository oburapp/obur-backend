"""Idempotent seeder for the platform's reference catalog.

Reference data — the venue category tree and its per-locale display names —
describes what the catalog should contain *now*, not what it contained on
some past date. It is expected to grow: adding a category means editing
`app/seeds/venue_categories.py` and the locale tables beside it, then running
this seeder again.

That is why it lives here and not in a migration. A migration is a frozen
record of a transition that already happened; running it again is not an
option, so a catalog that only ever grew through migrations would need one
new migration per entry and would silently ignore edits to the seed files.
See ADR-0012 in obur-docs for the full reasoning, and
`migrations/versions/61f7b67600da_*.py` for the migration this replaced.

Every write is an upsert keyed on the slug's deterministic id, so running
this against an already-seeded database is a no-op in effect. Rows are never
deleted: a category removed from the seed files stays in the database, since
venues may still reference it (`VENUE.category_id` is `NOT NULL`). Retiring a
category is a deliberate migration, not a side effect of editing a list.

**Not** part of normal application startup. Running it from the app's own
lifespan would race across instances and would require the running app to
hold write access it otherwise doesn't need. It is invoked explicitly — by
`just seed` locally, by the integration-test fixture, and as a deploy step
alongside `alembic upgrade head`.
"""

import asyncio
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import SUPPORTED_LOCALES
from app.models.venue_category import VenueCategory, VenueCategoryTranslation
from app.seeds.identity import venue_category_id
from app.seeds.locales import get_venue_category_names
from app.seeds.venue_categories import VENUE_CATEGORIES

logger = logging.getLogger(__name__)


def _category_rows() -> list[dict[str, object]]:
    """Build the VENUE_CATEGORY rows, resolving parent slugs to their ids."""
    return [
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


def _category_translation_rows() -> list[dict[str, object]]:
    """Build the VENUE_CATEGORY_TRANSLATION rows for every supported locale.

    A missing slug raises `KeyError` from the locale table rather than
    seeding a category with no display name — see app/seeds/locales.
    """
    return [
        {
            "category_id": venue_category_id(category.slug),
            "locale": locale,
            "name": get_venue_category_names(locale)[category.slug],
        }
        for locale in SUPPORTED_LOCALES
        for category in VENUE_CATEGORIES
    ]


async def seed_catalog(session: AsyncSession) -> None:
    """Upsert every reference-catalog row. Safe to run repeatedly.

    Parents are written before children in a single statement — the rows are
    ordered parent-first in `VENUE_CATEGORIES`, and PostgreSQL checks the
    self-referential foreign key per statement, not per row.
    """
    categories = pg_insert(VenueCategory).values(_category_rows())
    await session.execute(
        categories.on_conflict_do_update(
            index_elements=[VenueCategory.id],
            set_={
                "slug": categories.excluded.slug,
                "parent_id": categories.excluded.parent_id,
            },
        )
    )

    translations = pg_insert(VenueCategoryTranslation).values(
        _category_translation_rows()
    )
    await session.execute(
        translations.on_conflict_do_update(
            index_elements=[
                VenueCategoryTranslation.category_id,
                VenueCategoryTranslation.locale,
            ],
            set_={"name": translations.excluded.name},
        )
    )

    await session.commit()


async def _main() -> None:
    """Entry point for `just seed` and the deploy step."""
    # Imported here, not at module scope: importing app.core.database
    # constructs the engine as a side effect, which the test fixture (which
    # brings its own session) must not trigger.
    from app.core.database import async_session_factory, engine

    logging.basicConfig(level=logging.INFO)
    try:
        async with async_session_factory() as session:
            await seed_catalog(session)
    finally:
        await engine.dispose()
    logger.info(
        "Seeded %d venue categories across %d locale(s)",
        len(VENUE_CATEGORIES),
        len(SUPPORTED_LOCALES),
    )


if __name__ == "__main__":
    asyncio.run(_main())
