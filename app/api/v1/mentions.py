"""Mention endpoints (ADR-0019 in obur-docs): who the authenticated user
can mention, for the `@` dropdown.

The server re-checks every mention on submission regardless; this only
lets a client offer the right people in the first place.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.visibility import VisibilityValue
from app.models.user import User
from app.schemas.user import MAX_USERNAME_LENGTH, UserSummaryResponse
from app.services import mention as mention_service

router = APIRouter(prefix="/users", tags=["mentions"])


@router.get("/me/mentionable")
async def list_mentionable_users(
    visibility: VisibilityValue,
    q: str = Query(default="", max_length=MAX_USERNAME_LENGTH),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[UserSummaryResponse]:
    """People you can mention in a check-in with `visibility`, whose
    username starts with `q`: mutual followers who can see it. Always
    empty for `private`.
    """
    users = await mention_service.list_mentionable_users(
        session,
        author_id=current_user.id,
        visibility=visibility,
        username_prefix=q,
        limit=limit,
        offset=offset,
    )
    return [UserSummaryResponse.model_validate(user) for user in users]
