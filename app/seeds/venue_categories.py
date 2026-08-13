"""Canonical VENUE_CATEGORY seed data — language-independent.

Display names live per-locale under app/seeds/locales/, keyed by `slug`.
Adding a category means adding it here, then adding its name to every
module under app/seeds/locales/.

Order matters: a category must appear after its parent, since the seed
migration deletes rows in reverse of this order on downgrade to satisfy
the self-referential foreign key.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VenueCategorySeed:
    slug: str
    parent_slug: str | None = None


VENUE_CATEGORIES: tuple[VenueCategorySeed, ...] = (
    VenueCategorySeed(slug="food"),
    VenueCategorySeed(slug="kebap", parent_slug="food"),
    VenueCategorySeed(slug="pide", parent_slug="food"),
    VenueCategorySeed(slug="doner", parent_slug="food"),
    VenueCategorySeed(slug="fast-food", parent_slug="food"),
    VenueCategorySeed(slug="cafe"),
    VenueCategorySeed(slug="bar"),
    VenueCategorySeed(slug="dessert"),
    VenueCategorySeed(slug="bakery"),
)
