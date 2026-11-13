"""Schemas for check-in resources."""

from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.ratings import MAX_RATING, MIN_RATING
from app.core.visibility import Visibility, VisibilityValue

MAX_NOTE_LENGTH = 2000


def _ensure_known_timezone(name: str) -> str:
    """Reject anything the server can't resolve as an IANA timezone.

    `visited_tz` is fed to `ZoneInfo` to find the visitor's own "today"
    (app.services.checkin), so an unknown name has to stop here as a 422,
    not surface there as an unhandled error.
    """
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown IANA timezone: {name!r}") from e
    return name


TimezoneName = Annotated[str, AfterValidator(_ensure_known_timezone)]


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
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    photo_url: str | None = None
    visibility: VisibilityValue = Visibility.PUBLIC
    visited_at: date
    visited_tz: TimezoneName
    # The draft this submission came from, deleted in the same
    # transaction. Not stored on the check-in and not part of the
    # idempotency hash; a draft that no longer exists is not an error
    # (ADR-0018 in obur-docs).
    draft_id: UUID | None = None


class CheckinUpdateRequest(BaseModel):
    """Payload to update a check-in. Every field is optional — only
    fields actually present in the request are changed (see
    app.services.checkin.update_checkin).
    """

    rating_taste: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_service: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_ambiance: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_value: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)
    photo_url: str | None = None
    visibility: VisibilityValue | None = None
    visited_at: date | None = None


class MentionResponse(BaseModel):
    """One `@[<user_id>]` token in a note. `username` is the person's
    current one, or None once the mention is no longer active (a block, a
    visibility change, a hidden account); clients then show a localised
    placeholder such as "Obur user" (ADR-0019 in obur-docs).
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    username: str | None


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
    # Every token in `note`, in order. Filled by
    # app.api.v1.checkin_presenter, never by `model_validate` alone.
    mentions: list[MentionResponse] = Field(default_factory=list)
