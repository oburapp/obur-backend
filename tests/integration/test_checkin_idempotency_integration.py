"""Integration tests for idempotent check-in submission and the draft
deletion that comes with it (ADR-0018 in obur-docs), against the real
database.
"""

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine, set_current_user_identity
from app.exceptions import (
    CheckinDraftNotFoundError,
    CheckinNotFoundError,
    FutureVisitDateError,
    IdempotencyKeyReusedError,
    IdempotencyRequestInProgressError,
)
from app.models.checkin import Checkin
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services import checkin_draft as draft_service
from app.services.checkin_idempotency import acquire_submission_lock

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_TZ = "Europe/Istanbul"
_FAR_FUTURE = date(2999, 1, 1)


async def _create_user(session: AsyncSession) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    session.add(user)
    await session.flush()
    await set_current_user_identity(session, user.id)
    return user


async def _create_venue(session: AsyncSession, added_by: User) -> Venue:
    venue = Venue(
        name="Cihangir Kahvesi",
        lat=41.0317,
        lng=28.9823,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def _submit(
    session: AsyncSession, user: User, venue: Venue, key: UUID, **overrides: Any
) -> Checkin:
    fields: dict[str, Any] = {
        "rating_taste": 4,
        "rating_service": 3,
        "rating_ambiance": 3,
        "rating_value": 2,
        "visited_at": date.today(),
        "visited_tz": _TZ,
    }
    fields.update(overrides)
    return await checkin_service.create_checkin(
        session, user_id=user.id, idempotency_key=key, venue_id=venue.id, **fields
    )


async def _checkin_count(session: AsyncSession, user: User) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Checkin).where(Checkin.user_id == user.id)
    )
    return count or 0


async def test_a_retry_with_the_same_key_returns_the_original_checkin(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    key = uuid4()

    first = await _submit(db_session, user, venue, key)
    retry = await _submit(db_session, user, venue, key)

    assert retry.id == first.id
    assert await _checkin_count(db_session, user) == 1


async def test_a_key_reused_with_different_content_is_rejected(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    key = uuid4()
    await _submit(db_session, user, venue, key, rating_taste=4)

    with pytest.raises(IdempotencyKeyReusedError):
        await _submit(db_session, user, venue, key, rating_taste=1)
    assert await _checkin_count(db_session, user) == 1


async def test_a_retry_after_the_checkin_was_deleted_does_not_recreate_it(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    key = uuid4()
    checkin = await _submit(db_session, user, venue, key)
    await checkin_service.soft_delete_checkin(db_session, checkin.id, current_user=user)

    with pytest.raises(CheckinNotFoundError):
        await _submit(db_session, user, venue, key)
    assert await _checkin_count(db_session, user) == 1


async def test_the_same_key_from_two_users_creates_two_checkins(
    db_session: AsyncSession,
) -> None:
    alice = await _create_user(db_session)
    venue = await _create_venue(db_session, alice)
    bob = await _create_user(db_session)
    key = uuid4()

    await set_current_user_identity(db_session, alice.id)
    from_alice = await _submit(db_session, alice, venue, key)
    await set_current_user_identity(db_session, bob.id)
    from_bob = await _submit(db_session, bob, venue, key)

    assert from_alice.id != from_bob.id


async def test_a_concurrent_request_with_the_same_key_gets_in_progress(
    db_session: AsyncSession,
) -> None:
    """A second, real connection stands in for a request still running:
    it holds the key's lock in an open transaction while this one tries.
    """
    user_id, key = uuid4(), uuid4()
    async with engine.connect() as other_connection:
        await other_connection.begin()
        other = AsyncSession(bind=other_connection)
        await acquire_submission_lock(other, user_id=user_id, idempotency_key=key)

        with pytest.raises(IdempotencyRequestInProgressError):
            await acquire_submission_lock(
                db_session, user_id=user_id, idempotency_key=key
            )
        await other.close()


async def test_submitting_from_a_draft_deletes_the_draft(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    draft = await draft_service.create_draft(
        db_session, user_id=user.id, fields={"venue_id": venue.id}
    )

    await _submit(db_session, user, venue, uuid4(), draft_id=draft.id)

    with pytest.raises(CheckinDraftNotFoundError):
        await draft_service.get_draft(db_session, user_id=user.id, draft_id=draft.id)


async def test_submitting_with_a_draft_that_no_longer_exists_still_creates(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)

    checkin = await _submit(db_session, user, venue, uuid4(), draft_id=uuid4())

    assert checkin.id is not None


async def test_a_failed_submission_leaves_the_draft_in_place(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    draft = await draft_service.create_draft(db_session, user_id=user.id, fields={})

    with pytest.raises(FutureVisitDateError):
        await _submit(
            db_session, user, venue, uuid4(), visited_at=_FAR_FUTURE, draft_id=draft.id
        )

    found = await draft_service.get_draft(
        db_session, user_id=user.id, draft_id=draft.id
    )
    assert found.id == draft.id


async def test_submitting_with_someone_elses_draft_id_leaves_their_draft(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    draft = await draft_service.create_draft(db_session, user_id=owner.id, fields={})
    submitter = await _create_user(db_session)
    venue = await _create_venue(db_session, submitter)

    await _submit(db_session, submitter, venue, uuid4(), draft_id=draft.id)

    await set_current_user_identity(db_session, owner.id)
    found = await draft_service.get_draft(
        db_session, user_id=owner.id, draft_id=draft.id
    )
    assert found.id == draft.id
