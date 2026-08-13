"""Canonical GLOBAL_PRODUCT_TYPE seed data — language-independent.

Display names live per-locale under app/seeds/locales/, keyed by `slug`.
Each product type's `category_slug` must match a slug defined in
app/seeds/venue_categories.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalProductTypeSeed:
    slug: str
    category_slug: str


GLOBAL_PRODUCT_TYPES: tuple[GlobalProductTypeSeed, ...] = (
    GlobalProductTypeSeed(slug="kusbasili-pide", category_slug="pide"),
    GlobalProductTypeSeed(slug="kiymali-pide", category_slug="pide"),
    GlobalProductTypeSeed(slug="adana-kebap", category_slug="kebap"),
    GlobalProductTypeSeed(slug="urfa-kebap", category_slug="kebap"),
    GlobalProductTypeSeed(slug="iskender", category_slug="kebap"),
    GlobalProductTypeSeed(slug="tavuk-doner", category_slug="doner"),
    GlobalProductTypeSeed(slug="et-doner", category_slug="doner"),
    GlobalProductTypeSeed(slug="filter-coffee", category_slug="cafe"),
    GlobalProductTypeSeed(slug="turkish-coffee", category_slug="cafe"),
    GlobalProductTypeSeed(slug="latte", category_slug="cafe"),
    GlobalProductTypeSeed(slug="baklava", category_slug="dessert"),
    GlobalProductTypeSeed(slug="kunefe", category_slug="dessert"),
)
