"""Venue category catalog: the platform's only classification dimension.

Reads are locale-aware — a category's display name lives in
`VENUE_CATEGORY_TRANSLATION`, keyed by locale, rather than on the row (see
the PDD's "Translation tables over embedded strings" decision). A name
missing in the requested locale falls back to `DEFAULT_LOCALE` rather than
disappearing, so a partially translated catalog degrades to readable
instead of blank.

The catalog is team-curated and small by construction, so it is fetched
whole rather than paged: it is a tree, and half a tree is not a usable
answer for the pickers and filters that read it. `MAX_CATALOG_SIZE` keeps
that assumption honest instead of trusting it.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import DEFAULT_LOCALE
from app.models.venue_category import VenueCategory, VenueCategoryTranslation

# The ceiling that lets this endpoint skip pagination. Not a limit anyone
# should be near: it exists so that if the catalog ever grows into
# something that genuinely needs paging, a test says so rather than a
# client quietly receiving a truncated tree.
MAX_CATALOG_SIZE = 300


@dataclass(frozen=True)
class CategoryNode:
    """One category and its children, with its name already resolved."""

    id: uuid.UUID
    slug: str
    name: str
    children: tuple["CategoryNode", ...]


async def resolve_names(session: AsyncSession, locale: str) -> dict[uuid.UUID, str]:
    """Return each category's display name in `locale`, falling back to
    `DEFAULT_LOCALE` where the requested locale has no row.

    Both locales are fetched in one query rather than two: the fallback is
    needed often enough (any newly added category before its translations
    catch up) that a second round trip for it isn't worth saving.
    """
    wanted = {locale, DEFAULT_LOCALE}
    result = await session.execute(
        select(VenueCategoryTranslation).where(
            VenueCategoryTranslation.locale.in_(wanted)
        )
    )

    by_locale: dict[str, dict[uuid.UUID, str]] = defaultdict(dict)
    for translation in result.scalars().all():
        by_locale[translation.locale][translation.category_id] = translation.name

    return {**by_locale[DEFAULT_LOCALE], **by_locale[locale]}


def _build_tree(
    categories: list[VenueCategory], names: dict[uuid.UUID, str]
) -> tuple[CategoryNode, ...]:
    """Assemble the flat rows into roots-with-children.

    A category whose name is missing in every locale is skipped rather
    than rendered blank — and so are its children, since a subtree hanging
    off an unnamed parent has nowhere to appear in a picker.
    """
    children_of: dict[uuid.UUID | None, list[VenueCategory]] = defaultdict(list)
    for category in categories:
        children_of[category.parent_id].append(category)

    def build(parent_id: uuid.UUID | None) -> tuple[CategoryNode, ...]:
        return tuple(
            CategoryNode(
                id=category.id,
                slug=category.slug,
                name=names[category.id],
                children=build(category.id),
            )
            for category in children_of[parent_id]
            if category.id in names
        )

    return build(None)


async def list_category_tree(
    session: AsyncSession, *, locale: str
) -> tuple[CategoryNode, ...]:
    """Return the whole category tree, names resolved into `locale`.

    Ordered by slug within each level so the client renders a stable list
    without having to sort localized names itself.
    """
    result = await session.execute(select(VenueCategory).order_by(VenueCategory.slug))
    categories = list(result.scalars().all())

    names = await resolve_names(session, locale)
    return _build_tree(categories, names)
