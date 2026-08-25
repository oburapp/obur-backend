"""Custom exception classes, one module per service domain."""

from app.exceptions.auth_exceptions import (
    AuthError,
    InvalidTokenError,
    InvalidWebhookSignatureError,
)
from app.exceptions.checkin_exceptions import (
    CheckinError,
    CheckinNotFoundError,
    FutureVisitDateError,
    NotCheckinOwnerError,
)
from app.exceptions.social_exceptions import (
    BookmarkNotFoundError,
    CloseFriendNotFoundError,
    DuplicateListItemError,
    FollowNotFoundError,
    LikeNotFoundError,
    ListError,
    ListItemNotFoundError,
    ListNotFoundError,
    NotAFollowerError,
    NotListOwnerError,
    SelfFollowError,
    SocialError,
)
from app.exceptions.user_exceptions import (
    AccountNotFrozenError,
    UserError,
    UsernameChangedTooRecentlyError,
    UsernameTakenError,
)
from app.exceptions.venue_exceptions import (
    DuplicateVenueNearbyError,
    NotVenueSaveOwnerError,
    VenueCategoryNotFoundError,
    VenueError,
    VenueNotEligibleForVerificationError,
    VenueNotFoundError,
    VenueSaveNotFoundError,
)

__all__ = [
    "AccountNotFrozenError",
    "AuthError",
    "BookmarkNotFoundError",
    "CheckinError",
    "CheckinNotFoundError",
    "CloseFriendNotFoundError",
    "DuplicateListItemError",
    "DuplicateVenueNearbyError",
    "FollowNotFoundError",
    "FutureVisitDateError",
    "InvalidTokenError",
    "InvalidWebhookSignatureError",
    "LikeNotFoundError",
    "ListError",
    "ListItemNotFoundError",
    "ListNotFoundError",
    "NotAFollowerError",
    "NotCheckinOwnerError",
    "NotListOwnerError",
    "NotVenueSaveOwnerError",
    "SelfFollowError",
    "SocialError",
    "UserError",
    "UsernameChangedTooRecentlyError",
    "UsernameTakenError",
    "VenueCategoryNotFoundError",
    "VenueError",
    "VenueNotEligibleForVerificationError",
    "VenueNotFoundError",
    "VenueSaveNotFoundError",
]
