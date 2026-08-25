"""Custom exceptions for the venue domain."""

import uuid


class VenueError(Exception):
    """Base class for venue-domain errors."""


class VenueNotFoundError(VenueError):
    """Raised when a venue id doesn't match any row."""


class DuplicateVenueNearbyError(VenueError):
    """Raised when a venue already exists within the duplicate-detection
    radius of the requested coordinates — see the PDD's "Venue Identity"
    section and `app.services.venue._DUPLICATE_RADIUS_METERS`.
    """

    def __init__(self, nearby_venue_id: uuid.UUID) -> None:
        self.nearby_venue_id = nearby_venue_id
        super().__init__(
            f"a venue already exists near this location: {nearby_venue_id}"
        )


class VenueCategoryNotFoundError(VenueError):
    """Raised when a venue references a category id that doesn't exist."""


class VenueNotEligibleForVerificationError(VenueError):
    """Raised when an admin attempts to verify a venue that hasn't yet
    reached the required independent-check-in threshold — see
    `app.services.venue._MIN_CHECKINS_FOR_ADMIN_VERIFICATION` and
    ADR-0009 in obur-docs. The threshold is a filter, not a formality:
    it keeps the admin queue limited to venues with real community
    traction, so it isn't bypassable by an admin's own say-so.
    """


class VenueSaveNotFoundError(VenueError):
    """Raised when a venue save id doesn't match any (visible) row."""


class NotVenueSaveOwnerError(VenueError):
    """Raised when a non-owner, non-admin user attempts to modify or
    delete a venue save.
    """
