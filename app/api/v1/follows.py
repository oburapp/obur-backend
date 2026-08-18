"""Follow-facing endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.exceptions import FollowNotFoundError, SelfFollowError
from app.models.user import User
from app.schemas.user import UserSummaryResponse
from app.services import follow as follow_service

router = APIRouter(prefix="/users", tags=["follows"])


@router.post("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def follow_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Follow another user. Idempotent."""
    try:
        await follow_service.follow_user(
            session, follower_id=current_user.id, following_id=user_id
        )
    except SelfFollowError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        ) from e


@router.delete("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Stop following another user."""
    try:
        await follow_service.unfollow_user(
            session, follower_id=current_user.id, following_id=user_id
        )
    except FollowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not following this user"
        ) from e


@router.delete("/me/followers/{follower_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_follower(
    follower_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove one of the authenticated user's own followers."""
    try:
        await follow_service.remove_follower(
            session, user_id=current_user.id, follower_id=follower_id
        )
    except FollowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not a follower"
        ) from e


@router.get("/{user_id}/followers")
async def list_followers(
    user_id: UUID,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[UserSummaryResponse]:
    """List the users who follow `user_id`."""
    followers = await follow_service.list_followers(
        session, user_id, limit=limit, offset=offset
    )
    return [UserSummaryResponse.model_validate(user) for user in followers]


@router.get("/{user_id}/following")
async def list_following(
    user_id: UUID,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[UserSummaryResponse]:
    """List the users `user_id` follows."""
    following = await follow_service.list_following(
        session, user_id, limit=limit, offset=offset
    )
    return [UserSummaryResponse.model_validate(user) for user in following]
