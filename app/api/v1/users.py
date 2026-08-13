"""User-facing endpoints."""

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user's own profile."""
    return UserResponse.model_validate(current_user)
