"""Schemas for user resources."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    """Public shape of a User. Never includes auth_provider/auth_provider_id."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    username: str
    email: str | None
    bio: str | None
    avatar_url: str | None
    city: str | None
    country_code: str | None
    locale: str
    timezone: str | None
    role: str
    status: str
    created_at: datetime


class UserSummaryResponse(BaseModel):
    """Lightweight public shape of a User, for appearing in someone
    else's followers/following/close-friends list. Deliberately omits
    `email` and other fields with no reason to be visible to anyone but
    the user themselves — see `UserResponse` for that fuller shape.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    username: str
    bio: str | None
    avatar_url: str | None
