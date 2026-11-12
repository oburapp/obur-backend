"""Idempotent check-in submission (ADR-0018 in obur-docs), following the
IETF Idempotency-Key header draft
(draft-ietf-httpapi-idempotency-key-header).

A client generates a UUID when the user taps Save and sends it unchanged
on every retry of that submission. The server stores it on the check-in
together with a hash of the submitted content, so a retry resolves to the
original row instead of creating a duplicate, and a key reused with
different content is rejected instead of silently answered with the
wrong check-in.

Two requests with the same key arriving at once are serialised by a
transaction-scoped advisory lock: the second one gets
`IdempotencyRequestInProgressError` (409) rather than blocking on the
unique index, as the draft specifies.
"""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    CheckinNotFoundError,
    IdempotencyKeyReusedError,
    IdempotencyRequestInProgressError,
)
from app.models.checkin import Checkin

# Exactly the content a client submits for a check-in. `draft_id` is
# deliberately absent: it says where the submission came from, not what
# the check-in is. Adding a field to `Checkin` means deciding whether it
# belongs here.
HASHED_FIELDS = (
    "venue_id",
    "rating_taste",
    "rating_service",
    "rating_ambiance",
    "rating_value",
    "note",
    "photo_url",
    "visibility",
    "visited_at",
    "visited_tz",
)

# Prefixed into the advisory lock id so it can never coincide with a lock
# taken for an unrelated purpose.
_LOCK_NAMESPACE = "checkin-idempotency"
# pg_try_advisory_xact_lock takes a signed 64-bit key.
_LOCK_ID_BYTES = 8


def payload_hash(fields: dict[str, Any]) -> str:
    """SHA-256 of the hashed fields, in a canonical form: sorted keys,
    values as strings, so the same content always yields the same digest
    whatever order or Python type it arrived in.
    """
    canonical = {
        name: None if fields.get(name) is None else str(fields[name])
        for name in HASHED_FIELDS
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _lock_id(user_id: uuid.UUID, idempotency_key: uuid.UUID) -> int:
    seed = f"{_LOCK_NAMESPACE}:{user_id}:{idempotency_key}".encode()
    digest = hashlib.sha256(seed).digest()[:_LOCK_ID_BYTES]
    return int.from_bytes(digest, "big", signed=True)


async def acquire_submission_lock(
    session: AsyncSession, *, user_id: uuid.UUID, idempotency_key: uuid.UUID
) -> None:
    """Take the per-key lock for the rest of the current transaction.

    Raises `IdempotencyRequestInProgressError` if another transaction
    holds it, meaning a request with the same key is still running.
    """
    acquired = await session.scalar(
        select(func.pg_try_advisory_xact_lock(_lock_id(user_id, idempotency_key)))
    )
    if not acquired:
        raise IdempotencyRequestInProgressError(
            f"a request with idempotency key {idempotency_key} is in progress"
        )


async def find_previous_submission(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    idempotency_key: uuid.UUID,
    content_hash: str,
) -> Checkin | None:
    """Return the check-in an earlier request with this key created, or
    None if this is the first request with it.

    Raises `CheckinNotFoundError` if that check-in has since been
    soft-deleted: recreating it would undo the user's own deletion, and
    returning it would expose deleted content.
    Raises `IdempotencyKeyReusedError` if it was created from different
    content.
    """
    result = await session.execute(
        select(Checkin).where(
            Checkin.user_id == user_id,
            Checkin.idempotency_key == idempotency_key,
        )
    )
    previous = result.scalar_one_or_none()
    if previous is None:
        return None
    if previous.deleted_at is not None:
        raise CheckinNotFoundError(f"checkin not found: {previous.id}")
    if previous.idempotency_payload_hash != content_hash:
        raise IdempotencyKeyReusedError(
            f"idempotency key {idempotency_key} was used with different content"
        )
    return previous
