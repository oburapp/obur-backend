"""Integration tests for app.services.checkin against the real test
database — ownership/admin authorization, privacy filtering, and the
soft/hard delete distinction all depend on real DB state.
"""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import (
    CheckinNotFoundError,
    FutureVisitDateError,
    NotCheckinOwnerError,
    VenueNotFoundError,
)
from app.models.checkin import Checkin
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_LAT = 40.9905
_LNG = 29.0234
_TZ = "Europe/Istanbul"


async def _create_user(session: AsyncSession, *, role: str = UserRole.USER) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_venue(session: AsyncSession, added_by: User) -> Venue:
    # Venue creation now requires an authenticated identity (RLS,
    # migration c1d5a8f042e7).
    await set_current_user_identity(session, added_by.id)
    venue = Venue(
        name="Kadıköy Kahve Durağı",
        lat=_LAT,
        lng=_LNG,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def test_create_checkin_persists_and_is_retrievable(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)

    await set_current_user_identity(db_session, user.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=user.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        note="harika bir yer",
    )

    fetched = await checkin_service.get_checkin(db_session, checkin.id, viewer=user)
    assert fetched.note == "harika bir yer"
    assert fetched.rating_taste == 4
    assert fetched.rating_service == 3
    assert fetched.rating_ambiance == 3
    assert fetched.rating_value == 2


async def test_create_checkin_raises_when_venue_does_not_exist(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)

    with pytest.raises(VenueNotFoundError):
        await checkin_service.create_checkin(
            db_session,
            user_id=user.id,
            venue_id=uuid4(),
            rating_taste=4,
            rating_service=3,
            rating_ambiance=3,
            rating_value=2,
            visited_at=date.today(),
            visited_tz=_TZ,
        )


async def test_create_checkin_raises_on_future_visit_date(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    venue = await _create_venue(db_session, user)

    with pytest.raises(FutureVisitDateError):
        await checkin_service.create_checkin(
            db_session,
            user_id=user.id,
            venue_id=venue.id,
            rating_taste=4,
            rating_service=3,
            rating_ambiance=3,
            rating_value=2,
            visited_at=date.today() + timedelta(days=1),
            visited_tz=_TZ,
        )


async def test_get_checkin_hides_private_checkin_from_other_users(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    await set_current_user_identity(db_session, other_user.id)
    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=other_user)

    await set_current_user_identity(db_session, owner.id)
    fetched = await checkin_service.get_checkin(db_session, checkin.id, viewer=owner)
    assert fetched.id == checkin.id


async def test_get_checkin_reveals_private_checkin_to_admin(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    await set_current_user_identity(db_session, admin.id)
    fetched = await checkin_service.get_checkin(db_session, checkin.id, viewer=admin)
    assert fetched.id == checkin.id


async def test_get_checkin_reveals_close_friends_checkin_only_to_close_friends(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    close_friend_user = await _create_user(db_session)
    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, close_friend_user.id)
    await follow_service.follow_user(
        db_session, follower_id=close_friend_user.id, following_id=owner.id
    )
    await set_current_user_identity(db_session, owner.id)
    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=close_friend_user.id
    )
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.CLOSE_FRIENDS,
    )

    await set_current_user_identity(db_session, close_friend_user.id)
    fetched = await checkin_service.get_checkin(
        db_session, checkin.id, viewer=close_friend_user
    )
    assert fetched.id == checkin.id

    await set_current_user_identity(db_session, stranger.id)
    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=stranger)


async def test_list_checkins_for_venue_filters_private_checkins(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PUBLIC,
    )
    private_checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    await set_current_user_identity(db_session, other_user.id)
    as_stranger = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=other_user, limit=20, offset=0
    )
    assert all(c.id != private_checkin.id for c in as_stranger)
    assert len(as_stranger) == 1

    await set_current_user_identity(db_session, owner.id)
    as_owner = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=owner, limit=20, offset=0
    )
    assert any(c.id == private_checkin.id for c in as_owner)
    assert len(as_owner) == 2


async def test_list_checkins_for_user_filters_private_checkins(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    await set_current_user_identity(db_session, other_user.id)
    as_stranger = await checkin_service.list_checkins_for_user(
        db_session, owner.id, viewer=other_user, limit=20, offset=0
    )
    await set_current_user_identity(db_session, owner.id)
    as_owner = await checkin_service.list_checkins_for_user(
        db_session, owner.id, viewer=owner, limit=20, offset=0
    )

    assert as_stranger == []
    assert len(as_owner) == 1


async def test_update_checkin_persists_changes_for_the_owner(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    updated = await checkin_service.update_checkin(
        db_session, checkin.id, current_user=owner, updates={"note": "değişti"}
    )

    assert updated.note == "değişti"


async def test_update_checkin_raises_for_non_owner(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    await set_current_user_identity(db_session, other_user.id)
    with pytest.raises(NotCheckinOwnerError):
        await checkin_service.update_checkin(
            db_session,
            checkin.id,
            current_user=other_user,
            updates={"note": "başkası düzenlemeye çalıştı"},
        )


async def test_update_checkin_by_non_owner_on_a_private_checkin_returns_not_found(
    db_session: AsyncSession,
) -> None:
    """Existence-leak fix: a stranger who can't even see a private
    checkin must get the same `CheckinNotFoundError` a nonexistent id
    would — never `NotCheckinOwnerError`, which would confirm the id
    belongs to something real (see app.core.authz.ensure_visible_and_owned).
    """
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=Visibility.PRIVATE,
    )

    await set_current_user_identity(db_session, stranger.id)
    with pytest.raises(CheckinNotFoundError):
        await checkin_service.update_checkin(
            db_session, checkin.id, current_user=stranger, updates={"note": "x"}
        )


async def test_soft_delete_excludes_checkin_from_listings_and_lookup(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    await checkin_service.soft_delete_checkin(
        db_session, checkin.id, current_user=owner
    )

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=owner)

    listing = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=owner, limit=20, offset=0
    )
    assert listing == []

    # The row itself still exists — this was a soft delete.
    result = await db_session.execute(select(Checkin).where(Checkin.id == checkin.id))
    assert result.scalar_one().deleted_at is not None


async def test_hard_delete_removes_the_row_entirely(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
    )

    await checkin_service.hard_delete_checkin(db_session, checkin.id)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.get_checkin(db_session, checkin.id, viewer=owner)

    result = await db_session.execute(select(Checkin).where(Checkin.id == checkin.id))
    assert result.scalars().all() == []


async def test_hard_delete_can_purge_an_already_soft_deleted_checkin(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await checkin_service.create_checkin(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
    )
    await checkin_service.soft_delete_checkin(
        db_session, checkin.id, current_user=owner
    )

    await checkin_service.hard_delete_checkin(db_session, checkin.id)

    with pytest.raises(CheckinNotFoundError):
        await checkin_service.hard_delete_checkin(db_session, checkin.id)
