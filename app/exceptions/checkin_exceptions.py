"""Custom exceptions for the check-in domain."""


class CheckinError(Exception):
    """Base class for check-in-domain errors."""


class CheckinNotFoundError(CheckinError):
    """Raised when a check-in id doesn't match any (non-deleted) row."""


class FutureVisitDateError(CheckinError):
    """Raised when `visited_at` is after the visitor's own local today —
    see `app.services.checkin.create_checkin`.
    """


class NotCheckinOwnerError(CheckinError):
    """Raised when a non-owner, non-admin user attempts to modify or
    delete a check-in — see `app.core.authz`.
    """
