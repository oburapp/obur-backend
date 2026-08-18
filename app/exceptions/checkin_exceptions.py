"""Custom exceptions for the check-in domain."""


class CheckinError(Exception):
    """Base class for check-in-domain errors."""


class CheckinNotFoundError(CheckinError):
    """Raised when a check-in id doesn't match any (non-deleted) row."""


class FutureVisitDateError(CheckinError):
    """Raised when `visited_at` is after the visitor's own local today —
    see `app.services.checkin.create_checkin`.
    """


class DuplicateProductRatingError(CheckinError):
    """Raised when the same product is rated more than once in a single
    check-in.
    """


class ProductNotAtVenueError(CheckinError):
    """Raised when a product being rated doesn't belong to the venue
    being checked into.
    """


class EmptyProductListError(CheckinError):
    """Raised when a check-in is submitted with no rated products."""


class NotCheckinOwnerError(CheckinError):
    """Raised when a non-owner, non-admin user attempts to modify or
    delete a check-in — see `app.core.authz`.
    """
