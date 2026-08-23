"""Schemas for check-in resources."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.ratings import MAX_RATING, MIN_RATING
from app.core.visibility import Visibility, VisibilityValue

_MAX_NOTE_LENGTH = 2000


class CheckinCreateRequest(BaseModel):
    """Payload to create a check-in. `user_id` is never accepted from
    the client — it's always the authenticated user (see
    app.core.auth.get_current_user).
    """

    venue_id: UUID
    rating_taste: int = Field(ge=MIN_RATING, le=MAX_RATING)
    rating_service: int = Field(ge=MIN_RATING, le=MAX_RATING)
    rating_ambiance: int = Field(ge=MIN_RATING, le=MAX_RATING)
    rating_value: int = Field(ge=MIN_RATING, le=MAX_RATING)
    note: str | None = Field(default=None, max_length=_MAX_NOTE_LENGTH)
    photo_url: str | None = None
    visibility: VisibilityValue = Visibility.PUBLIC
    visited_at: date
    visited_tz: str


class CheckinUpdateRequest(BaseModel):
    """Payload to update a check-in. Every field is optional — only
    fields actually present in the request are changed (see
    app.services.checkin.update_checkin).
    """

    rating_taste: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_service: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_ambiance: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_value: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    note: str | None = Field(default=None, max_length=_MAX_NOTE_LENGTH)
    photo_url: str | None = None
    visibility: VisibilityValue | None = None
    visited_at: date | None = None


class CheckinResponse(BaseModel):
    """Public shape of a Checkin."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    venue_id: UUID
    rating_taste: int
    rating_service: int
    rating_ambiance: int
    rating_value: int
    note: str | None
    photo_url: str | None
    visibility: str
    visited_at: date
    visited_tz: str
    created_at: datetime
