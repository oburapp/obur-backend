"""Mute-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.models.user import User
from app.schemas.user import UserSummaryResponse
from app.services import mute as mute_service

router = APIRouter(prefix="/users", tags=["mutes"])


@router.post("/{user_id}/mute", status_code=status.HTTP_204_NO_CONTENT)
async def mute_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Mute `user_id`. Idempotent."""
    await mute_service.create_mute(session, user_id=current_user.id, muted_id=user_id)


@router.delete("/{user_id}/mute", status_code=status.HTTP_204_NO_CONTENT)
async def unmute_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Unmute `user_id`."""
    await mute_service.remove_mute(session, user_id=current_user.id, muted_id=user_id)


@router.get("/me/mutes")
async def list_muted_users(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[UserSummaryResponse]:
    """List the users the authenticated user has muted."""
    muted = await mute_service.list_muted_users(
        session, current_user.id, limit=limit, offset=offset
    )
    return [UserSummaryResponse.model_validate(user) for user in muted]
