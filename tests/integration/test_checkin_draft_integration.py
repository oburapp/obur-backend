"""Integration tests for app.services.checkin_draft against the real
database (ADR-0018 in obur-docs): autosave, read-time expiry, lazy
cleanup, and owner scoping.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import CheckinDraftNotFoundError, VenueNotFoundError
from app.models.checkin_draft import CheckinDraft
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import checkin_draft as draft_service
from app.services.checkin_draft import DRAFT_LIFETIME

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_TZ = "Europe/Istanbul"
_LIST_PAGE = {"limit": 20, "offset": 0}
# How far past (or short of) the expiry boundary a test moves a draft.
_MARGIN = timedelta(minutes=1)


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
        name="Moda Kahvecisi",
        lat=40.9876,
        lng=29.0257,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def _age_draft(
    session: AsyncSession, draft: CheckinDraft, age: timedelta
) -> None:
    """Move a draft's last edit `age` into the past."""
    await session.execute(
        update(CheckinDraft)
        .where(CheckinDraft.id == draft.id)
        .values(updated_at=func.now() - age)
    )


async def test_create_draft_with_no_fields_defaults_visibility_to_public(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)

    draft = await draft_service.create_draft(db_session, user_id=user.id, fields={})

    assert draft.visibility == Visibility.PUBLIC
    assert draft.venue_id is None
    assert draft.visited_at is None


async def test_create_draft_rejects_an_unknown_venue(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)

    with pytest.raises(VenueNotFoundError):
        await draft_service.create_draft(
            db_session, user_id=user.id, fields={"venue_id": uuid4()}
        )


async def test_update_draft_applies_fields_and_last_write_wins(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)
    draft = await draft_service.create_draft(db_session, user_id=user.id, fields={})

    await draft_service.update_draft(
        db_session,
        user_id=user.id,
        draft_id=draft.id,
        updates={"venue_id": venue.id, "rating_taste": 2, "note": "phone"},
    )
    updated = await draft_service.update_draft(
        db_session,
        user_id=user.id,
        draft_id=draft.id,
        updates={"note": "laptop", "visibility": Visibility.CLOSE_FRIENDS},
    )

    assert updated.venue_id == venue.id
    assert updated.rating_taste == 2
    assert updated.note == "laptop"
    assert updated.visibility == Visibility.CLOSE_FRIENDS


async def test_update_draft_rejects_an_unknown_venue(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    draft = await draft_service.create_draft(db_session, user_id=user.id, fields={})

    with pytest.raises(VenueNotFoundError):
        await draft_service.update_draft(
            db_session,
            user_id=user.id,
            draft_id=draft.id,
            updates={"venue_id": uuid4()},
        )


async def test_an_empty_update_still_renews_the_draft_lifetime(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    draft = await draft_service.create_draft(db_session, user_id=user.id, fields={})
    await _age_draft(db_session, draft, DRAFT_LIFETIME - _MARGIN)

    renewed = await draft_service.update_draft(
        db_session, user_id=user.id, draft_id=draft.id, updates={}
    )

    assert renewed.updated_at == await db_session.scalar(select(func.now()))


async def test_an_expired_draft_cannot_be_read_or_updated(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    draft = await draft_service.create_draft(db_session, user_id=user.id, fields={})
    await _age_draft(db_session, draft, DRAFT_LIFETIME + _MARGIN)

    with pytest.raises(CheckinDraftNotFoundError):
        await draft_service.get_draft(db_session, user_id=user.id, draft_id=draft.id)
    with pytest.raises(CheckinDraftNotFoundError):
        await draft_service.update_draft(
            db_session, user_id=user.id, draft_id=draft.id, updates={"note": "x"}
        )


async def test_a_draft_just_inside_its_lifetime_is_still_readable(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    draft = await draft_service.create_draft(db_session, user_id=user.id, fields={})
    await _age_draft(db_session, draft, DRAFT_LIFETIME - _MARGIN)

    found = await draft_service.get_draft(
        db_session, user_id=user.id, draft_id=draft.id
    )

    assert found.id == draft.id


async def test_listing_drafts_hides_and_physically_deletes_expired_ones(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    fresh = await draft_service.create_draft(db_session, user_id=user.id, fields={})
    stale = await draft_service.create_draft(db_session, user_id=user.id, fields={})
    await _age_draft(db_session, stale, DRAFT_LIFETIME + _MARGIN)

    listed = await draft_service.list_drafts(db_session, user.id, **_LIST_PAGE)

    assert [draft.id for draft in listed] == [fresh.id]
    remaining = await db_session.scalar(
        select(func.count()).where(CheckinDraft.id == stale.id)
    )
    assert remaining == 0


async def test_listing_drafts_orders_most_recently_edited_first(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    older = await draft_service.create_draft(db_session, user_id=user.id, fields={})
    newer = await draft_service.create_draft(db_session, user_id=user.id, fields={})
    await _age_draft(db_session, older, timedelta(days=1))

    listed = await draft_service.list_drafts(db_session, user.id, **_LIST_PAGE)

    assert [draft.id for draft in listed] == [newer.id, older.id]


async def test_another_users_draft_behaves_as_if_it_does_not_exist(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    draft = await draft_service.create_draft(db_session, user_id=owner.id, fields={})
    stranger = await _create_user(db_session)

    with pytest.raises(CheckinDraftNotFoundError):
        await draft_service.get_draft(
            db_session, user_id=stranger.id, draft_id=draft.id
        )
    with pytest.raises(CheckinDraftNotFoundError):
        await draft_service.delete_draft(
            db_session, user_id=stranger.id, draft_id=draft.id
        )
    assert await draft_service.list_drafts(db_session, stranger.id, **_LIST_PAGE) == []


async def test_delete_draft_removes_it(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    draft = await draft_service.create_draft(
        db_session,
        user_id=user.id,
        fields={"visited_at": date.today(), "visited_tz": _TZ},
    )

    await draft_service.delete_draft(db_session, user_id=user.id, draft_id=draft.id)

    with pytest.raises(CheckinDraftNotFoundError):
        await draft_service.get_draft(db_session, user_id=user.id, draft_id=draft.id)
