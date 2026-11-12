"""Unit tests for app.services.checkin_idempotency and
app.core.idempotency (ADR-0018 in obur-docs).
"""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.idempotency import get_idempotency_key
from app.exceptions import (
    CheckinNotFoundError,
    IdempotencyKeyInvalidError,
    IdempotencyKeyMissingError,
    IdempotencyKeyReusedError,
    IdempotencyRequestInProgressError,
)
from app.models.checkin import Checkin
from app.services.checkin_idempotency import (
    HASHED_FIELDS,
    acquire_submission_lock,
    find_previous_submission,
    payload_hash,
)

_VENUE_ID = uuid4()
_HASH_LENGTH = 64
_SIGNED_64_BIT_MIN = -(2**63)
_SIGNED_64_BIT_MAX = 2**63 - 1


def _fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "venue_id": _VENUE_ID,
        "rating_taste": 4,
        "rating_service": 3,
        "rating_ambiance": 3,
        "rating_value": 2,
        "note": None,
        "photo_url": None,
        "visibility": "public",
        "visited_at": date(2026, 11, 12),
        "visited_tz": "Europe/Istanbul",
    }
    fields.update(overrides)
    return fields


def _session_returning(previous: Checkin | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = previous
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def test_payload_hash_is_a_stable_hex_sha256() -> None:
    assert payload_hash(_fields()) == payload_hash(_fields())
    assert len(payload_hash(_fields())) == _HASH_LENGTH


def test_payload_hash_ignores_value_types_and_fields_outside_the_contract() -> None:
    as_strings = _fields(venue_id=str(_VENUE_ID), visited_at="2026-11-12")
    with_draft = {**_fields(), "draft_id": uuid4()}

    assert payload_hash(as_strings) == payload_hash(_fields())
    assert payload_hash(with_draft) == payload_hash(_fields())


@pytest.mark.parametrize("field", HASHED_FIELDS)
def test_payload_hash_changes_when_any_hashed_field_changes(field: str) -> None:
    changed = _fields(**{field: "something else"})

    assert payload_hash(changed) != payload_hash(_fields())


def test_payload_hash_tells_an_absent_note_from_an_empty_one() -> None:
    assert payload_hash(_fields(note=None)) != payload_hash(_fields(note=""))


async def test_acquire_submission_lock_raises_when_the_lock_is_taken() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=False)

    with pytest.raises(IdempotencyRequestInProgressError):
        await acquire_submission_lock(session, user_id=uuid4(), idempotency_key=uuid4())


async def test_acquire_submission_lock_uses_a_signed_64_bit_lock_id() -> None:
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=True)

    await acquire_submission_lock(session, user_id=uuid4(), idempotency_key=uuid4())

    statement = session.scalar.await_args.args[0]
    (lock_id,) = statement.compile().params.values()
    assert _SIGNED_64_BIT_MIN <= lock_id <= _SIGNED_64_BIT_MAX


async def test_find_previous_submission_returns_none_for_a_new_key() -> None:
    session = _session_returning(None)

    previous = await find_previous_submission(
        session, user_id=uuid4(), idempotency_key=uuid4(), content_hash="h"
    )

    assert previous is None


async def test_find_previous_submission_returns_a_matching_checkin() -> None:
    checkin = Checkin(idempotency_payload_hash="h", deleted_at=None)
    session = _session_returning(checkin)

    previous = await find_previous_submission(
        session, user_id=uuid4(), idempotency_key=uuid4(), content_hash="h"
    )

    assert previous is checkin


async def test_find_previous_submission_rejects_different_content() -> None:
    session = _session_returning(Checkin(idempotency_payload_hash="a", deleted_at=None))

    with pytest.raises(IdempotencyKeyReusedError):
        await find_previous_submission(
            session, user_id=uuid4(), idempotency_key=uuid4(), content_hash="b"
        )


async def test_find_previous_submission_treats_a_deleted_checkin_as_gone() -> None:
    deleted = Checkin(idempotency_payload_hash="h", deleted_at=datetime.now(UTC))
    session = _session_returning(deleted)

    with pytest.raises(CheckinNotFoundError):
        await find_previous_submission(
            session, user_id=uuid4(), idempotency_key=uuid4(), content_hash="h"
        )


def test_get_idempotency_key_parses_a_uuid() -> None:
    key = uuid4()

    assert get_idempotency_key(str(key)) == key


def test_get_idempotency_key_rejects_a_missing_header() -> None:
    with pytest.raises(IdempotencyKeyMissingError):
        get_idempotency_key(None)


def test_get_idempotency_key_rejects_a_non_uuid() -> None:
    with pytest.raises(IdempotencyKeyInvalidError):
        get_idempotency_key("retry-1")
