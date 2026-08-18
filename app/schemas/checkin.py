"""Schemas for check-in resources."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.ratings import MAX_RATING, MIN_RATING
from app.models.checkin import Checkin
from app.models.checkin_product import CheckinProduct

_MAX_NOTE_LENGTH = 2000


class ProductRatingRequest(BaseModel):
    """One product's rating within a check-in being created."""

    product_id: UUID
    rating: int = Field(ge=MIN_RATING, le=MAX_RATING)


class CheckinCreateRequest(BaseModel):
    """Payload to create a check-in. `user_id` is never accepted from
    the client — it's always the authenticated user (see
    app.core.auth.get_current_user).
    """

    venue_id: UUID
    products: list[ProductRatingRequest] = Field(min_length=1)
    rating_service: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_ambiance: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_value: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    note: str | None = Field(default=None, max_length=_MAX_NOTE_LENGTH)
    photo_url: str | None = None
    is_public: bool = True
    visited_at: date
    visited_tz: str


class CheckinUpdateRequest(BaseModel):
    """Payload to update a check-in. Every field is optional — only
    fields actually present in the request are changed (see
    app.services.checkin.update_checkin). The product list isn't
    editable through this endpoint.
    """

    rating_service: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_ambiance: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    rating_value: int | None = Field(default=None, ge=MIN_RATING, le=MAX_RATING)
    note: str | None = Field(default=None, max_length=_MAX_NOTE_LENGTH)
    photo_url: str | None = None
    is_public: bool | None = None
    visited_at: date | None = None


class CheckinProductResponse(BaseModel):
    """Public shape of a CheckinProduct."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    rating: int


class CheckinResponse(BaseModel):
    """Public shape of a Checkin, with its rated products attached.

    Never built via plain `model_validate(checkin)` — `Checkin` has no
    `products` relationship (see app/models/checkin.py), so callers
    must fetch products separately (batched across a whole list, to
    avoid N+1 — see app.services.checkin.get_products_for_checkins) and
    combine them via `from_models`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    venue_id: UUID
    rating_service: int | None
    rating_ambiance: int | None
    rating_value: int | None
    note: str | None
    photo_url: str | None
    is_public: bool
    visited_at: date
    visited_tz: str
    created_at: datetime
    products: list[CheckinProductResponse]

    @classmethod
    def from_models(
        cls, checkin: Checkin, products: list[CheckinProduct]
    ) -> CheckinResponse:
        return cls(
            id=checkin.id,
            user_id=checkin.user_id,
            venue_id=checkin.venue_id,
            rating_service=checkin.rating_service,
            rating_ambiance=checkin.rating_ambiance,
            rating_value=checkin.rating_value,
            note=checkin.note,
            photo_url=checkin.photo_url,
            is_public=checkin.is_public,
            visited_at=checkin.visited_at,
            visited_tz=checkin.visited_tz,
            created_at=checkin.created_at,
            products=[
                CheckinProductResponse.model_validate(product) for product in products
            ],
        )
