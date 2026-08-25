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
    # Required from Phase 9 onward regardless of how it was resolved
    # (Google Places address components via client-side Autocomplete, or
    # typed by hand in the manual-entry form), see ADR-0009 in obur-docs.
    district: str = Field(min_length=1, max_length=255)
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
    # Null for venues created before Phase 9 shipped, no backfill, see
    # ADR-0009 in obur-docs.
    district: str | None
    address_note: str | None
    google_places_id: str | None
    # Null once the account that added this venue has been deleted — the
    # venue survives, the attribution doesn't (see app/models/venue.py).
    added_by: UUID | None
    category_id: UUID
    # Localized display text for `category_id`, resolved per request (see
    # app.core.locale). `category_id` stays the thing to key logic off;
    # this is display only, and is null where the catalog has no name in
    # any supported locale.
    category_name: str | None = None
    city: str | None
    country_code: str | None
    timezone: str | None
    # Cosmetic only, never gates discoverability, ranking, or search.
    is_verified: bool
    # The business itself has closed, per an admin acting on a report.
    # Shown transparently rather than hidden, unlike is_suspended, which
    # RLS already keeps a non-admin caller from ever seeing true for.
    is_active: bool
    is_suspended: bool
    created_at: datetime


class NearbyVenueResponse(BaseModel):
    """Returned when venue creation is rejected as a likely duplicate —
    lets the client show "did you mean this one?" and resubmit with
    `confirm_duplicate=True` if it's genuinely a different venue.
    """

    nearby_venue_id: UUID
