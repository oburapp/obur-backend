"""Schemas for user resources."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.i18n import SUPPORTED_LOCALES

_MAX_DISPLAY_NAME_LENGTH = 50
_MAX_USERNAME_LENGTH = 30
_MAX_BIO_LENGTH = 300
_MAX_CITY_LENGTH = 100
# Letters, digits, underscore and dot — the character set handles across
# comparable platforms converge on. Anything that could be confused with a
# path segment or a mention delimiter is out, since `username` is what
# profile URLs and @mentions key off of (PDD §7).
_USERNAME_PATTERN = r"^[a-zA-Z0-9._]+$"


class UserUpdateRequest(BaseModel):
    """Payload to edit one's own profile. Every field is optional — only
    fields actually present are changed, so a partial update never clears
    what it didn't mention.

    `role` and `status` are deliberately absent: neither is ever settable
    through a user-facing endpoint (PDD §7, §11). `email` is absent too —
    it belongs to the auth provider and arrives via its webhook.
    """

    display_name: str | None = Field(
        default=None, min_length=1, max_length=_MAX_DISPLAY_NAME_LENGTH
    )
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=_MAX_USERNAME_LENGTH,
        pattern=_USERNAME_PATTERN,
    )
    bio: str | None = Field(default=None, max_length=_MAX_BIO_LENGTH)
    avatar_url: str | None = None
    city: str | None = Field(default=None, max_length=_MAX_CITY_LENGTH)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    locale: str | None = Field(default=None, pattern="|".join(SUPPORTED_LOCALES))
    timezone: str | None = None


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
