"""Hashtag page endpoints (ADR-0019 in obur-docs): a tag's public
check-ins and a tag's public lists, separately, so a client can show them
as tabs or merge them as it chooses.

`tag` is matched case-insensitively, so `/hashtags/Kahve/...` and
`/hashtags/kahve/...` are the same page. Readable without signing in.
"""

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.checkin_presenter import checkin_responses
from app.core.auth import get_optional_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.text_tokens import MAX_HASHTAG_LENGTH
from app.models.user import User
from app.schemas.checkin import CheckinResponse
from app.schemas.list import ListResponse
from app.services import hashtag as hashtag_service

router = APIRouter(prefix="/hashtags", tags=["hashtags"])

_TAG = Path(min_length=1, max_length=MAX_HASHTAG_LENGTH)


@router.get("/{tag}/checkins")
async def list_hashtag_checkins(
    tag: str = _TAG,
    viewer: User | None = Depends(get_optional_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CheckinResponse]:
    """Public check-ins carrying `tag`, newest first."""
    checkins = await hashtag_service.list_checkins_for_hashtag(
        session, tag, viewer=viewer, limit=limit, offset=offset
    )
    return await checkin_responses(session, checkins)


@router.get("/{tag}/lists")
async def list_hashtag_lists(
    tag: str = _TAG,
    viewer: User | None = Depends(get_optional_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[ListResponse]:
    """Public lists carrying `tag`, newest first."""
    lists = await hashtag_service.list_lists_for_hashtag(
        session, tag, viewer=viewer, limit=limit, offset=offset
    )
    return [ListResponse.model_validate(venue_list) for venue_list in lists]
