"""Reading the `Idempotency-Key` request header (ADR-0018 in obur-docs).

A missing or malformed key is rejected with 400 before any work starts,
as the IETF Idempotency-Key header draft specifies, rather than falling
through to FastAPI's generic 422 validation response.
"""

import uuid

from fastapi import Header

from app.exceptions import IdempotencyKeyInvalidError, IdempotencyKeyMissingError

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


def get_idempotency_key(
    raw_key: str | None = Header(default=None, alias=IDEMPOTENCY_KEY_HEADER),
) -> uuid.UUID:
    """Return the request's idempotency key as a UUID.

    Raises `IdempotencyKeyMissingError` if the header is absent and
    `IdempotencyKeyInvalidError` if it is not a UUID.
    """
    if raw_key is None:
        raise IdempotencyKeyMissingError(f"{IDEMPOTENCY_KEY_HEADER} header missing")
    try:
        return uuid.UUID(raw_key)
    except ValueError as e:
        raise IdempotencyKeyInvalidError(
            f"{IDEMPOTENCY_KEY_HEADER} header is not a UUID"
        ) from e
