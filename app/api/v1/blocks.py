"""Block-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.models.user import User
from app.schemas.user import UserSummaryResponse
from app.services import block as block_service

router = APIRouter(prefix="/users", tags=["blocks"])


@router.post("/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def block_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Block `user_id`. Idempotent."""
    await block_service.create_block(
        session, blocker_id=current_user.id, blocked_id=user_id
    )


@router.delete("/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Unblock `user_id`. Only the blocker may do this (PDD §11)."""
    await block_service.remove_block(
        session, blocker_id=current_user.id, blocked_id=user_id
    )


@router.get("/me/blocks")
async def list_blocked_users(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[UserSummaryResponse]:
    """List the users the authenticated user has blocked."""
    blocked = await block_service.list_blocked_users(
        session, limit=limit, offset=offset
    )
    return [UserSummaryResponse.model_validate(user) for user in blocked]
