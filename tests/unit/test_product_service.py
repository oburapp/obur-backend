"""Unit tests for app.services.product — every DB call is mocked."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import (
    GlobalProductTypeNotFoundError,
    ProductNotFoundError,
    VenueNotFoundError,
)
from app.models.global_product_type import GlobalProductType
from app.models.product import Product
from app.models.venue import Venue
from app.services import product as product_service


def _session_with_get(*results: object) -> AsyncMock:
    """A session whose `.get()` returns `results` in order, one per call."""
    session = AsyncMock()
    session.add = MagicMock()  # AsyncSession.add() is sync, not a coroutine
    session.get = AsyncMock(side_effect=results)
    return session


async def test_create_product_raises_when_venue_not_found() -> None:
    session = _session_with_get(None)

    with pytest.raises(VenueNotFoundError):
        await product_service.create_product(
            session, venue_id=uuid4(), global_type_id=uuid4(), name="Kuşbaşılı Pide"
        )

    session.add.assert_not_called()


async def test_create_product_raises_when_global_type_not_found() -> None:
    session = _session_with_get(MagicMock(spec=Venue), None)

    with pytest.raises(GlobalProductTypeNotFoundError):
        await product_service.create_product(
            session, venue_id=uuid4(), global_type_id=uuid4(), name="Kuşbaşılı Pide"
        )

    session.add.assert_not_called()


async def test_create_product_succeeds_when_venue_and_type_exist() -> None:
    session = _session_with_get(
        MagicMock(spec=Venue), MagicMock(spec=GlobalProductType)
    )

    product = await product_service.create_product(
        session, venue_id=uuid4(), global_type_id=uuid4(), name="Kuşbaşılı Pide"
    )

    assert product.name == "Kuşbaşılı Pide"
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


async def test_get_product_returns_product_when_found() -> None:
    product = Product(id=uuid4(), name="Kuşbaşılı Pide")
    session = _session_with_get(product)

    result = await product_service.get_product(session, product.id)

    assert result is product


async def test_get_product_raises_when_not_found() -> None:
    session = _session_with_get(None)

    with pytest.raises(ProductNotFoundError):
        await product_service.get_product(session, uuid4())


async def test_list_products_for_venue_returns_paginated_results() -> None:
    products = [Product(id=uuid4(), name="A"), Product(id=uuid4(), name="B")]
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = products
    session.execute.return_value = result

    returned = await product_service.list_products_for_venue(
        session, uuid4(), limit=20, offset=0
    )

    assert returned == products
