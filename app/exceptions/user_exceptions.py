"""Custom exceptions for the user/profile domain."""

from datetime import datetime


class UserError(Exception):
    """Base class for user-domain errors."""


class UsernameTakenError(UserError):
    """Raised when a requested handle already belongs to someone else."""


class UsernameChangedTooRecentlyError(UserError):
    """Raised when a handle change falls inside the rate-limit window —
    see `app.services.user.USERNAME_CHANGE_INTERVAL_DAYS`.

    Carries `allowed_at` as a value rather than only in the message, so the
    HTTP layer can say when without parsing the exception's text.
    """

    def __init__(self, allowed_at: datetime) -> None:
        self.allowed_at = allowed_at
        super().__init__(f"username can be changed again at {allowed_at.isoformat()}")


class AccountNotFrozenError(UserError):
    """Raised when reactivation is attempted on an account that isn't
    frozen. A suspended account is deliberately not reactivatable this
    way: suspension is admin-only and never user-reversible (PDD §11).
    """


class UserNotFoundError(UserError):
    """Raised when a user id doesn't match any row: an admin action
    (e.g. suspension) on an id that doesn't exist.
    """
