"""Schemas for check-in draft resources (ADR-0018 in obur-docs).

Every content field is optional, since a draft is incomplete by
definition. The limits that do apply (rating range, note length) are the
same constants a real check-in uses, so a draft can never hold a value
its own submission would reject for being out of range.
"""

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.ratings import MAX_RATING, MIN_RATING
from app.core.visibility import Visibility, VisibilityValue
from app.schemas.checkin import MAX_NOTE_LENGTH, TimezoneName

_VISIT_FIELDS = frozenset({"visited_at", "visited_tz"})
_UNPAIRED_VISIT_MESSAGE = (
    "visited_at and visited_tz must be set together: the timezone describes "
    "where the visit happened, so it is written by the device that picks the date"
)


def _ensure_visit_fields_paired(
    visited_at: date | None, visited_tz: str | None
) -> None:
    if (visited_at is None) != (visited_tz is None):
        raise ValueError(_UNPAIRED_VISIT_MESSAGE)


class CheckinDraftCreateRequest(BaseModel):
    """Payload to start a draft. May be empty; `user_id` always comes from
    the authenticated user.
    """

    venue_id: UUID | None = None
    rating_taste: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_service: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_ambiance: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_value: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    photo_url: str | None = None
    visibility: VisibilityValue = Visibility.PUBLIC
    visited_at: date | None = None
    visited_tz: TimezoneName | None = None

    @model_validator(mode="after")
    def _visit_fields_paired(self) -> Self:
        _ensure_visit_fields_paired(self.visited_at, self.visited_tz)
        return self


class CheckinDraftUpdateRequest(BaseModel):
    """An autosave. Only fields present in the request change; sending a
    field as null clears it, except `visibility`, which always has a value.
    """

    venue_id: UUID | None = None
    rating_taste: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_service: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_ambiance: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_value: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    photo_url: str | None = None
    visibility: VisibilityValue | None = None
    visited_at: date | None = None
    visited_tz: TimezoneName | None = None

    @model_validator(mode="after")
    def _visibility_never_cleared(self) -> Self:
        if "visibility" in self.model_fields_set and self.visibility is None:
            raise ValueError("visibility cannot be cleared, only changed")
        return self

    @model_validator(mode="after")
    def _visit_fields_paired(self) -> Self:
        sent = _VISIT_FIELDS & self.model_fields_set
        if sent and sent != _VISIT_FIELDS:
            raise ValueError(_UNPAIRED_VISIT_MESSAGE)
        _ensure_visit_fields_paired(self.visited_at, self.visited_tz)
        return self


class CheckinDraftResponse(BaseModel):
    """Public shape of a CheckinDraft. Only ever returned to its owner."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    venue_id: UUID | None
    rating_taste: int | None
    rating_service: int | None
    rating_ambiance: int | None
    rating_value: int | None
    note: str | None
    photo_url: str | None
    visibility: str
    visited_at: date | None
    visited_tz: str | None
    updated_at: datetime
    created_at: datetime
