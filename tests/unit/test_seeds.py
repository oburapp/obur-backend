"""Tests for the seed-data package: deterministic ids and locale lookups."""

import pytest

from app.seeds.global_product_types import GLOBAL_PRODUCT_TYPES
from app.seeds.identity import global_product_type_id, venue_category_id
from app.seeds.locales import get_global_product_type_names, get_venue_category_names
from app.seeds.venue_categories import VENUE_CATEGORIES


def test_venue_category_id_is_deterministic() -> None:
    assert venue_category_id("cafe") == venue_category_id("cafe")


def test_venue_category_id_differs_by_slug() -> None:
    assert venue_category_id("cafe") != venue_category_id("bar")


def test_global_product_type_id_is_deterministic() -> None:
    assert global_product_type_id("filter-coffee") == global_product_type_id(
        "filter-coffee"
    )


def test_global_product_type_id_differs_from_venue_category_id_for_same_slug() -> None:
    # "cafe" is never used as a product type slug, but this guards against
    # the two id functions ever colliding if it ever were.
    assert venue_category_id("cafe") != global_product_type_id("cafe")


def test_every_venue_category_has_a_turkish_name() -> None:
    names = get_venue_category_names("tr")

    for category in VENUE_CATEGORIES:
        assert category.slug in names


def test_every_global_product_type_has_a_turkish_name() -> None:
    names = get_global_product_type_names("tr")

    for product_type in GLOBAL_PRODUCT_TYPES:
        assert product_type.slug in names


def test_every_product_type_category_slug_exists_in_venue_categories() -> None:
    known_slugs = {category.slug for category in VENUE_CATEGORIES}

    for product_type in GLOBAL_PRODUCT_TYPES:
        assert product_type.category_slug in known_slugs


def test_every_category_parent_slug_exists_in_venue_categories() -> None:
    known_slugs = {category.slug for category in VENUE_CATEGORIES}

    for category in VENUE_CATEGORIES:
        if category.parent_slug is not None:
            assert category.parent_slug in known_slugs


def test_get_venue_category_names_raises_for_unsupported_locale() -> None:
    with pytest.raises(KeyError):
        get_venue_category_names("de")
