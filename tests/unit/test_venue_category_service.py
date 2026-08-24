"""Unit tests for the category tree builder — the DB is mocked.

The SQL itself is exercised against real seeded data in
tests/integration/test_venue_categories_endpoint_integration.py; what's
covered here is the assembly and the fallback rules, which are pure logic.
"""

import uuid
from uuid import uuid4

from app.models.venue_category import VenueCategory
from app.services.venue_category import CategoryNode, _build_tree


def _row(slug: str, parent_id: uuid.UUID | None = None) -> VenueCategory:
    """A detached VenueCategory. SQLAlchemy models construct fine without
    a session, so the builder can be tested on the real type.
    """
    return VenueCategory(id=uuid4(), slug=slug, parent_id=parent_id)


def test_build_tree_nests_children_under_their_parent() -> None:
    food = _row("food")
    doner = _row("doner", food.id)
    names = {food.id: "Yeme İçme", doner.id: "Dönerci"}

    tree = _build_tree([food, doner], names)

    assert [node.slug for node in tree] == ["food"]
    assert [child.slug for child in tree[0].children] == ["doner"]


def test_build_tree_returns_every_root() -> None:
    rows = [_row("food"), _row("cafe"), _row("bar")]
    names = {row.id: row.slug for row in rows}

    tree = _build_tree(rows, names)

    assert {node.slug for node in tree} == {"food", "cafe", "bar"}


def test_build_tree_skips_a_category_with_no_name_in_any_locale() -> None:
    """A blank label is worse than an absent one: it would render as an
    empty row in a picker with no way to tell what it selects.
    """
    food = _row("food")
    unnamed = _row("brand-new", food.id)

    tree = _build_tree([food, unnamed], {food.id: "Yeme İçme"})

    assert tree[0].children == ()


def test_build_tree_drops_the_subtree_under_an_unnamed_parent() -> None:
    """A named child hanging off an unnamed parent has nowhere to appear."""
    unnamed_parent = _row("mystery")
    child = _row("doner", unnamed_parent.id)

    tree = _build_tree([unnamed_parent, child], {child.id: "Dönerci"})

    assert tree == ()


def test_category_node_is_immutable() -> None:
    """The tree is built once per request and read many times; making it
    frozen keeps a caller from mutating a shared structure by accident.
    """
    node = CategoryNode(id=uuid4(), slug="food", name="Yeme İçme", children=())

    try:
        node.slug = "cafe"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("CategoryNode should be frozen")
