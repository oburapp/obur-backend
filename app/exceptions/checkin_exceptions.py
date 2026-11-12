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


class CheckinDraftNotFoundError(CheckinError):
    """Raised when a draft id doesn't match one of the caller's own
    unexpired drafts. Another user's draft looks identical to a missing
    one (ADR-0018 in obur-docs).
    """


class IdempotencyKeyMissingError(CheckinError):
    """Raised when a check-in submission has no `Idempotency-Key` header."""


class IdempotencyKeyInvalidError(CheckinError):
    """Raised when the `Idempotency-Key` header is not a UUID."""


class IdempotencyKeyReusedError(CheckinError):
    """Raised when a key already used for one check-in arrives with
    different content. Only a client bug produces this, so it is
    rejected rather than silently resolved to the original.
    """


class IdempotencyRequestInProgressError(CheckinError):
    """Raised when a request with the same key is still being processed."""
