"""Close-friends-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.exceptions import CloseFriendNotFoundError, NotAFollowerError
from app.models.user import User
from app.schemas.user import UserSummaryResponse
from app.services import close_friend as close_friend_service

router = APIRouter(prefix="/users", tags=["close-friends"])


@router.post("/me/close-friends/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_close_friend(
    friend_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Add one of the authenticated user's followers to their close
    friends. Idempotent.
    """
    try:
        await close_friend_service.add_close_friend(
            session, user_id=current_user.id, friend_id=friend_id
        )
    except NotAFollowerError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        ) from e


@router.delete("/me/close-friends/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_close_friend(
    friend_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove someone from the authenticated user's close friends."""
    try:
        await close_friend_service.remove_close_friend(
            session, user_id=current_user.id, friend_id=friend_id
        )
    except CloseFriendNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not a close friend"
        ) from e


@router.get("/me/close-friends")
async def list_close_friends(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[UserSummaryResponse]:
    """List the authenticated user's own close friends."""
    friends = await close_friend_service.list_close_friends(
        session, current_user.id, limit=limit, offset=offset
    )
    return [UserSummaryResponse.model_validate(user) for user in friends]
