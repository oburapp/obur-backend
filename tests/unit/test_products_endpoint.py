"""Tests for /api/v1/products — the product service is mocked."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import AsyncClient, Response
from pytest_mock import MockerFixture

from app.core.auth import get_current_user
from app.exceptions import (
    GlobalProductTypeNotFoundError,
    ProductNotFoundError,
    VenueNotFoundError,
)
from app.main import app
from app.models.product import Product
from app.models.user import User

_USER = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")


def _product(**overrides: object) -> Product:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "venue_id": uuid4(),
        "global_type_id": uuid4(),
        "name": "Kuşbaşılı Pide",
        "is_available": True,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Product(**defaults)


async def _post_product(client: AsyncClient, **overrides: object) -> Response:
    payload: dict[str, object] = {
        "venue_id": str(uuid4()),
        "global_type_id": str(uuid4()),
        "name": "Kuşbaşılı Pide",
    }
    payload.update(overrides)
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        return await client.post("/api/v1/products", json=payload)
    finally:
        app.dependency_overrides.clear()


async def test_create_product_returns_201_with_valid_payload(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    product = _product()
    mocker.patch(
        "app.api.v1.products.product_service.create_product",
        AsyncMock(return_value=product),
    )

    response = await _post_product(client)

    assert response.status_code == 201
    assert response.json()["name"] == "Kuşbaşılı Pide"


async def test_create_product_returns_404_when_venue_missing(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.products.product_service.create_product",
        AsyncMock(side_effect=VenueNotFoundError("nope")),
    )

    response = await _post_product(client)

    assert response.status_code == 404


async def test_create_product_returns_404_when_global_type_missing(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.products.product_service.create_product",
        AsyncMock(side_effect=GlobalProductTypeNotFoundError("nope")),
    )

    response = await _post_product(client)

    assert response.status_code == 404


async def test_list_products_returns_products_for_venue(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    venue_id = uuid4()
    products = [_product(venue_id=venue_id), _product(venue_id=venue_id)]
    mocker.patch(
        "app.api.v1.products.product_service.list_products_for_venue",
        AsyncMock(return_value=products),
    )

    response = await client.get("/api/v1/products", params={"venue_id": str(venue_id)})

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_product_returns_product_when_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    product = _product()
    mocker.patch(
        "app.api.v1.products.product_service.get_product",
        AsyncMock(return_value=product),
    )

    response = await client.get(f"/api/v1/products/{product.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(product.id)


async def test_get_product_returns_404_when_not_found(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.products.product_service.get_product",
        AsyncMock(side_effect=ProductNotFoundError("nope")),
    )

    response = await client.get(f"/api/v1/products/{uuid4()}")

    assert response.status_code == 404
