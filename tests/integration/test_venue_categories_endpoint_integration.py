"""The category catalog end to end, against the real seeded data.

This is what a client hits before anything else: the venue creation form
and Discover's filters both need the whole tree, so the shape and the
locale resolution are worth proving against real rows rather than mocks.
"""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES
from app.models.venue_category import VenueCategory
from app.seeds.venue_categories import VENUE_CATEGORIES
from app.services.venue_category import MAX_CATALOG_SIZE


def _flatten(nodes: list[dict]) -> list[dict]:
    return [
        node for item in nodes for node in [item, *_flatten(item.get("children", []))]
    ]


async def test_catalog_returns_every_seeded_category(client: AsyncClient) -> None:
    response = await client.get("/api/v1/venue-categories")

    assert response.status_code == 200
    slugs = {node["slug"] for node in _flatten(response.json())}
    assert slugs == {category.slug for category in VENUE_CATEGORIES}


async def test_catalog_nests_children_under_their_parent(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/venue-categories")

    root = next(node for node in response.json() if node["slug"] == "restaurant")
    assert "doner" in {child["slug"] for child in root["children"]}


async def test_catalog_defaults_to_turkish(client: AsyncClient) -> None:
    response = await client.get("/api/v1/venue-categories")

    root = next(node for node in response.json() if node["slug"] == "restaurant")
    assert root["name"] == "Restoran"


async def test_catalog_honours_accept_language(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/venue-categories",
        headers={"accept-language": "en-GB,en;q=0.9,tr;q=0.8"},
    )

    root = next(node for node in response.json() if node["slug"] == "restaurant")
    assert root["name"] == "Restaurant"


async def test_catalog_falls_back_for_an_unsupported_language(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/venue-categories", headers={"accept-language": "de"}
    )

    root = next(node for node in response.json() if node["slug"] == "restaurant")
    assert root["name"] == "Restoran"


async def test_catalog_is_a_constant_number_of_queries(
    client_with_db_session: AsyncClient, query_counter
) -> None:
    """The tree is assembled from two queries regardless of its size —
    one for the rows, one for every translation. A per-node lookup would
    scale with the catalog, and the catalog is the thing that grows.
    """
    query_counter.reset()
    await client_with_db_session.get("/api/v1/venue-categories")

    assert query_counter.count <= 3


async def test_seeded_catalog_stays_under_the_pagination_ceiling(
    db_session: AsyncSession,
) -> None:
    """The endpoint is deliberately unpaginated because the catalog is
    curated and bounded. This is what keeps that a fact rather than a
    promise: if the catalog ever outgrows the ceiling, this fails and the
    exception gets revisited instead of silently serving a huge response.
    """
    result = await db_session.execute(select(VenueCategory))

    assert len(result.scalars().all()) <= MAX_CATALOG_SIZE


async def test_every_category_is_named_in_every_supported_locale(
    client: AsyncClient,
) -> None:
    """A locale in `SUPPORTED_LOCALES` with missing names would silently
    fall back, making the language look half-implemented rather than
    failing loudly.
    """
    for locale in SUPPORTED_LOCALES:
        response = await client.get(
            "/api/v1/venue-categories", headers={"accept-language": locale}
        )
        names = {node["slug"]: node["name"] for node in _flatten(response.json())}
        assert len(names) == len(VENUE_CATEGORIES), locale

        if locale != DEFAULT_LOCALE:
            default = await client.get(
                "/api/v1/venue-categories",
                headers={"accept-language": DEFAULT_LOCALE},
            )
            default_names = {
                node["slug"]: node["name"] for node in _flatten(default.json())
            }
            # Not every name has to differ (a "Pizza" is a "Pizza"), but a
            # locale that matched the default everywhere would mean its
            # translations never loaded at all.
            assert names != default_names, locale


async def test_every_root_is_either_selectable_or_has_children(
    client: AsyncClient,
) -> None:
    """A root with no children and no generic leaf would be a dead branch:
    grouping that groups nothing, which nobody can pick. See ADR-0013.
    """
    tree = (await client.get("/api/v1/venue-categories")).json()

    assert tree
    for root in tree:
        assert root["children"], root["slug"]


async def test_the_generic_leaf_exists_exactly_where_it_should(
    client: AsyncClient,
) -> None:
    """`Kafe` and `Bar` are venue types people actually name, so each gets a
    leaf under its own root. `Restoran` and `Tatlı` are not — their generic
    forms are `lokanta` and `pastane` — so they deliberately have none.
    """
    tree = {
        node["slug"]: node
        for node in (await client.get("/api/v1/venue-categories")).json()
    }

    for root, expected in (
        ("cafe", "cafe-general"),
        ("bar", "bar-general"),
    ):
        assert expected in {child["slug"] for child in tree[root]["children"]}

    for root in ("restaurant", "dessert"):
        slugs = {child["slug"] for child in tree[root]["children"]}
        assert not any(slug.endswith("-general") for slug in slugs), root
