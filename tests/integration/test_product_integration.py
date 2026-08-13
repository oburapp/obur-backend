"""Integration tests for app.services.product against the real test database."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    GlobalProductTypeNotFoundError,
    ProductNotFoundError,
    VenueNotFoundError,
)
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import global_product_type_id, venue_category_id
from app.services import product as product_service

_CAFE_CATEGORY_ID = venue_category_id("cafe")
_FILTER_COFFEE_TYPE_ID = global_product_type_id("filter-coffee")


async def _create_venue(db_session: AsyncSession) -> Venue:
    user = User(auth_provider="clerk", auth_provider_id=f"user_{uuid4()}")
    db_session.add(user)
    await db_session.flush()

    venue = Venue(
        name="Kadıköy Kahve Durağı",
        lat=40.9905,
        lng=29.0234,
        category_id=_CAFE_CATEGORY_ID,
        added_by=user.id,
    )
    db_session.add(venue)
    await db_session.flush()
    return venue


async def test_create_product_persists_and_is_retrievable(
    db_session: AsyncSession,
) -> None:
    venue = await _create_venue(db_session)

    product = await product_service.create_product(
        db_session,
        venue_id=venue.id,
        global_type_id=_FILTER_COFFEE_TYPE_ID,
        name="Kadıköy Kahve Durağı — Filtre Kahve",
    )

    fetched = await product_service.get_product(db_session, product.id)
    assert fetched.id == product.id
    assert fetched.is_available is True


async def test_create_product_raises_when_venue_does_not_exist(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(VenueNotFoundError):
        await product_service.create_product(
            db_session,
            venue_id=uuid4(),
            global_type_id=_FILTER_COFFEE_TYPE_ID,
            name="Filtre Kahve",
        )


async def test_create_product_raises_when_global_type_does_not_exist(
    db_session: AsyncSession,
) -> None:
    venue = await _create_venue(db_session)

    with pytest.raises(GlobalProductTypeNotFoundError):
        await product_service.create_product(
            db_session,
            venue_id=venue.id,
            global_type_id=uuid4(),
            name="Filtre Kahve",
        )


async def test_get_product_raises_when_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(ProductNotFoundError):
        await product_service.get_product(db_session, uuid4())


async def test_list_products_for_venue_returns_only_that_venues_products(
    db_session: AsyncSession,
) -> None:
    venue_a = await _create_venue(db_session)
    venue_b = await _create_venue(db_session)
    await product_service.create_product(
        db_session,
        venue_id=venue_a.id,
        global_type_id=_FILTER_COFFEE_TYPE_ID,
        name="A'nın Filtre Kahvesi",
    )
    await product_service.create_product(
        db_session,
        venue_id=venue_b.id,
        global_type_id=_FILTER_COFFEE_TYPE_ID,
        name="B'nin Filtre Kahvesi",
    )

    results = await product_service.list_products_for_venue(
        db_session, venue_a.id, limit=20, offset=0
    )

    assert len(results) == 1
    assert results[0].name == "A'nın Filtre Kahvesi"
