"""Venue category catalog endpoint.

Public and unauthenticated: a client needs the catalog to render the venue
creation form and Discover's filters before anyone has signed in.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.locale import resolve_locale
from app.schemas.venue_category import VenueCategoryResponse
from app.services import venue_category as venue_category_service

router = APIRouter(prefix="/venue-categories", tags=["venue-categories"])


@router.get("")
async def list_venue_categories(
    locale: str = Depends(resolve_locale),
    session: AsyncSession = Depends(get_session),
) -> list[VenueCategoryResponse]:
    """Return the whole category tree, names resolved for this request.

    Deliberately unpaginated, the one exception to this codebase's
    pagination rule. The catalog is team-curated and bounded (see
    `MAX_CATALOG_SIZE`, which a test enforces), and it is a tree: a client
    that received half of one would render a broken picker rather than a
    shorter list. Locale comes from the signed-in user's own setting, or
    `Accept-Language` for anonymous callers.
    """
    tree = await venue_category_service.list_category_tree(session, locale=locale)
    return [VenueCategoryResponse.from_node(node) for node in tree]
