"""Schemas for venue resources."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class VenueCreateRequest(BaseModel):
    """Payload to create a venue. `added_by` is never accepted from the
    client — it's always the authenticated user (see
    app.core.auth.get_current_user).
    """

    name: str = Field(min_length=1, max_length=255)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    category_id: UUID
    address_note: str | None = None
    google_places_id: str | None = None
    city: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = None
    confirm_duplicate: bool = False


class VenueResponse(BaseModel):
    """Public shape of a Venue."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    lat: float
    lng: float
    address_note: str | None
    google_places_id: str | None
    # Null once the account that added this venue has been deleted — the
    # venue survives, the attribution doesn't (see app/models/venue.py).
    added_by: UUID | None
    category_id: UUID
    city: str | None
    country_code: str | None
    timezone: str | None
    status: str
    created_at: datetime


class NearbyVenueResponse(BaseModel):
    """Returned when venue creation is rejected as a likely duplicate —
    lets the client show "did you mean this one?" and resubmit with
    `confirm_duplicate=True` if it's genuinely a different venue.
    """

    nearby_venue_id: UUID
