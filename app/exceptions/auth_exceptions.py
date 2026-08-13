"""Custom exceptions for authentication and identity."""


class AuthError(Exception):
    """Base class for authentication-domain errors."""


class InvalidTokenError(AuthError):
    """Raised when a session token fails Clerk verification."""


class InvalidWebhookSignatureError(AuthError):
    """Raised when an incoming Clerk webhook's signature cannot be verified."""
