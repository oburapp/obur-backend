"""Product domain: venue-specific items linked to a GlobalProductType."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    GlobalProductTypeNotFoundError,
    ProductNotFoundError,
    VenueNotFoundError,
)
from app.models.global_product_type import GlobalProductType
from app.models.product import Product
from app.models.venue import Venue


async def create_product(
    session: AsyncSession,
    *,
    venue_id: uuid.UUID,
    global_type_id: uuid.UUID,
    name: str,
) -> Product:
    """Create a product at a venue.

    Raises `VenueNotFoundError` if `venue_id` doesn't exist, or
    `GlobalProductTypeNotFoundError` if `global_type_id` doesn't exist.
    """
    if await session.get(Venue, venue_id) is None:
        raise VenueNotFoundError(f"venue not found: {venue_id}")
    if await session.get(GlobalProductType, global_type_id) is None:
        raise GlobalProductTypeNotFoundError(
            f"global product type not found: {global_type_id}"
        )

    product = Product(venue_id=venue_id, global_type_id=global_type_id, name=name)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def get_product(session: AsyncSession, product_id: uuid.UUID) -> Product:
    """Return a product by id.

    Raises `ProductNotFoundError` if no such product exists.
    """
    product = await session.get(Product, product_id)
    if product is None:
        raise ProductNotFoundError(f"product not found: {product_id}")
    return product


async def list_products_for_venue(
    session: AsyncSession, venue_id: uuid.UUID, *, limit: int, offset: int
) -> list[Product]:
    """Return a venue's products ordered newest-first, paginated."""
    result = await session.execute(
        select(Product)
        .where(Product.venue_id == venue_id)
        .order_by(Product.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
