"""Custom exception classes, one module per service domain."""

from app.exceptions.auth_exceptions import (
    AuthError,
    InvalidTokenError,
    InvalidWebhookSignatureError,
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
    "DuplicateVenueNearbyError",
    "GlobalProductTypeNotFoundError",
    "InvalidTokenError",
    "InvalidWebhookSignatureError",
    "ProductError",
    "ProductNotFoundError",
    "VenueCategoryNotFoundError",
    "VenueError",
    "VenueNotFoundError",
]
