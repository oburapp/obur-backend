"""Tests for the seed-data package: deterministic ids and locale lookups."""

import pytest

from app.seeds.identity import venue_category_id
from app.seeds.locales import get_venue_category_names
from app.seeds.venue_categories import VENUE_CATEGORIES


def test_venue_category_id_is_deterministic() -> None:
    assert venue_category_id("cafe") == venue_category_id("cafe")


def test_venue_category_id_differs_by_slug() -> None:
    assert venue_category_id("cafe") != venue_category_id("bar")


def test_every_venue_category_has_a_turkish_name() -> None:
    names = get_venue_category_names("tr")

    for category in VENUE_CATEGORIES:
        assert category.slug in names


def test_every_category_parent_slug_exists_in_venue_categories() -> None:
    known_slugs = {category.slug for category in VENUE_CATEGORIES}

    for category in VENUE_CATEGORIES:
        if category.parent_slug is not None:
            assert category.parent_slug in known_slugs


def test_category_parents_precede_their_children() -> None:
    """The seeder writes every category in one statement, so a parent must
    appear before any child that references it — see app/seeds/runner.py.
    """
    seen: set[str] = set()

    for category in VENUE_CATEGORIES:
        if category.parent_slug is not None:
            assert category.parent_slug in seen, (
                f"{category.slug} precedes its parent {category.parent_slug}"
            )
        seen.add(category.slug)


def test_get_venue_category_names_raises_for_unsupported_locale() -> None:
    with pytest.raises(KeyError):
        get_venue_category_names("de")
