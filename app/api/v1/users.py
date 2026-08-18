"""User-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.models.user import User
from app.models.venue_save import VenueSaveTypeValue
from app.schemas.checkin import CheckinResponse
from app.schemas.list import ListResponse
from app.schemas.user import UserResponse
from app.schemas.venue_save import VenueSaveResponse
from app.services import bookmark as bookmark_service
from app.services import checkin as checkin_service
from app.services import list as list_service
from app.services import venue_save as venue_save_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user's own profile."""
    return UserResponse.model_validate(current_user)


@router.get("/{user_id}/checkins")
async def list_user_checkins(
    user_id: UUID,
    viewer: User | None = Depends(get_optional_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CheckinResponse]:
    """List a user's check-ins, newest first. Private check-ins are
    only included when the viewer is that same user or an admin.
    """
    checkins = await checkin_service.list_checkins_for_user(
        session, user_id, viewer=viewer, limit=limit, offset=offset
    )
    products_by_checkin = await checkin_service.get_products_for_checkins(
        session, [checkin.id for checkin in checkins]
    )
    return [
        CheckinResponse.from_models(checkin, products_by_checkin.get(checkin.id, []))
        for checkin in checkins
    ]


@router.get("/{user_id}/lists")
async def list_user_lists(
    user_id: UUID,
    viewer: User | None = Depends(get_optional_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ListResponse]:
    """List a user's lists, newest first. Private lists are only
    included when the viewer is that same user or an admin.
    """
    lists = await list_service.list_lists_for_user(
        session, user_id, viewer=viewer, limit=limit, offset=offset
    )
    return [ListResponse.model_validate(venue_list) for venue_list in lists]


@router.get("/{user_id}/venue-saves")
async def list_user_venue_saves(
    user_id: UUID,
    type: VenueSaveTypeValue | None = None,
    viewer: User | None = Depends(get_optional_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[VenueSaveResponse]:
    """List a user's venue saves, newest first, optionally filtered to
    one `type`. Private saves are only included when the viewer is that
    same user or an admin.
    """
    saves = await venue_save_service.list_venue_saves_for_user(
        session, user_id, type=type, viewer=viewer, limit=limit, offset=offset
    )
    return [VenueSaveResponse.model_validate(save) for save in saves]


@router.get("/me/bookmarks/checkins")
async def list_my_bookmarked_checkins(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CheckinResponse]:
    """List the authenticated user's own bookmarked check-ins, newest-
    bookmarked-first.
    """
    checkins = await bookmark_service.list_bookmarked_checkins(
        session, current_user.id, limit=limit, offset=offset
    )
    products_by_checkin = await checkin_service.get_products_for_checkins(
        session, [checkin.id for checkin in checkins]
    )
    return [
        CheckinResponse.from_models(checkin, products_by_checkin.get(checkin.id, []))
        for checkin in checkins
    ]


@router.get("/me/bookmarks/lists")
async def list_my_bookmarked_lists(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ListResponse]:
    """List the authenticated user's own bookmarked lists, newest-
    bookmarked-first.
    """
    lists = await bookmark_service.list_bookmarked_lists(
        session, current_user.id, limit=limit, offset=offset
    )
    return [ListResponse.model_validate(venue_list) for venue_list in lists]
