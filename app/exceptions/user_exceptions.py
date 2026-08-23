"""Custom exceptions for the user/profile domain."""


class UserError(Exception):
    """Base class for user-domain errors."""


class UsernameTakenError(UserError):
    """Raised when a requested handle already belongs to someone else."""


class UsernameChangedTooRecentlyError(UserError):
    """Raised when a handle change falls inside the rate-limit window —
    see `app.services.user.USERNAME_CHANGE_INTERVAL_DAYS`.
    """


class AccountNotFrozenError(UserError):
    """Raised when reactivation is attempted on an account that isn't
    frozen. A suspended account is deliberately not reactivatable this
    way: suspension is admin-only and never user-reversible (PDD §11).
    """
