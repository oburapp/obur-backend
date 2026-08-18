"""Schemas for user resources."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    """Public shape of a User. Never includes auth_provider/auth_provider_id."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str | None
    email: str | None
    bio: str | None
    avatar_url: str | None
    city: str | None
    country_code: str | None
    locale: str
    timezone: str | None
    role: str
    created_at: datetime
