"""Product-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.exceptions import (
    GlobalProductTypeNotFoundError,
    ProductNotFoundError,
    VenueNotFoundError,
)
from app.models.user import User
from app.schemas.product import ProductCreateRequest, ProductResponse
from app.services import product as product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    """Create a product at a venue."""
    try:
        product = await product_service.create_product(
            session,
            venue_id=payload.venue_id,
            global_type_id=payload.global_type_id,
            name=payload.name,
        )
    except VenueNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found"
        ) from e
    except GlobalProductTypeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product type not found"
        ) from e

    return ProductResponse.model_validate(product)


@router.get("")
async def list_products(
    venue_id: UUID,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ProductResponse]:
    """List a venue's products, paginated."""
    products = await product_service.list_products_for_venue(
        session, venue_id, limit=limit, offset=offset
    )
    return [ProductResponse.model_validate(product) for product in products]


@router.get("/{product_id}")
async def get_product(
    product_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    """Return a single product by id."""
    try:
        product = await product_service.get_product(session, product_id)
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        ) from e

    return ProductResponse.model_validate(product)
