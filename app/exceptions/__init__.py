"""Custom exception classes, one module per service domain."""

from app.exceptions.auth_exceptions import (
    AuthError,
    InvalidTokenError,
    InvalidWebhookSignatureError,
)
from app.exceptions.checkin_exceptions import (
    CheckinError,
    CheckinNotFoundError,
    DuplicateProductRatingError,
    EmptyProductListError,
    FutureVisitDateError,
    NotCheckinOwnerError,
    ProductNotAtVenueError,
)
from app.exceptions.venue_exceptions import (
    DuplicateVenueNearbyError,
    GlobalProductTypeNotFoundError,
    ProductError,
    ProductNotFoundError,
    VenueCategoryNotFoundError,
    VenueError,
    VenueNotFoundError,
)

__all__ = [
    "AuthError",
    "CheckinError",
    "CheckinNotFoundError",
    "DuplicateProductRatingError",
    "DuplicateVenueNearbyError",
    "EmptyProductListError",
    "FutureVisitDateError",
    "GlobalProductTypeNotFoundError",
    "InvalidTokenError",
    "InvalidWebhookSignatureError",
    "NotCheckinOwnerError",
    "ProductError",
    "ProductNotAtVenueError",
    "ProductNotFoundError",
    "VenueCategoryNotFoundError",
    "VenueError",
    "VenueNotFoundError",
]
