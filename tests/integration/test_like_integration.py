"""Integration tests for app.services.like against the real test
database — liking something requires the same visibility check as
viewing it, which only real DB state can exercise.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import CheckinNotFoundError, LikeNotFoundError, ListNotFoundError
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services import like as like_service
from app.services import list as list_service
from app.services import notification as notification_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_TZ = "Europe/Istanbul"


async def _create_user(session: AsyncSession) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
    )
    session.add(user)
    await session.flush()
    return user


async def _create_checkin(
    session: AsyncSession, owner: User, *, visibility: str = Visibility.PUBLIC
):
    # Venue creation now requires an authenticated identity (RLS,
    # migration c1d5a8f042e7). Callers already set `owner`'s identity
    # before this point in practice, but set it explicitly here too
    # rather than relying on that.
    await set_current_user_identity(session, owner.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
    )
    session.add(venue)
    await session.flush()
    return await checkin_service.create_checkin(
        session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
        visibility=visibility,
    )


async def test_like_checkin_is_idempotent(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    liker = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)

    await set_current_user_identity(db_session, liker.id)
    first = await like_service.like_checkin(db_session, checkin.id, current_user=liker)
    second = await like_service.like_checkin(db_session, checkin.id, current_user=liker)

    assert first.user_id == second.user_id
    count = await like_service.count_checkin_likes(db_session, checkin.id)
    assert count == 1


async def test_like_checkin_raises_when_invisible_to_the_liker(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    stranger = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner, visibility=Visibility.PRIVATE)

    await set_current_user_identity(db_session, stranger.id)
    with pytest.raises(CheckinNotFoundError):
        await like_service.like_checkin(db_session, checkin.id, current_user=stranger)


async def test_unlike_checkin_raises_when_never_liked(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    other_user = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)

    with pytest.raises(LikeNotFoundError):
        await like_service.unlike_checkin(
            db_session, checkin.id, current_user=other_user
        )


async def test_liking_someone_elses_checkin_creates_a_notification(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    liker = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)

    await set_current_user_identity(db_session, liker.id)
    await like_service.like_checkin(db_session, checkin.id, current_user=liker)

    await set_current_user_identity(db_session, owner.id)
    unread = await notification_service.count_unread_notifications(db_session, owner.id)
    assert unread == 1


async def test_liking_your_own_checkin_does_not_create_a_notification(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    checkin = await _create_checkin(db_session, owner)

    await like_service.like_checkin(db_session, checkin.id, current_user=owner)

    unread = await notification_service.count_unread_notifications(db_session, owner.id)
    assert unread == 0


async def test_unlike_checkin_removes_the_like(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    liker = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)
    await set_current_user_identity(db_session, liker.id)
    await like_service.like_checkin(db_session, checkin.id, current_user=liker)

    await like_service.unlike_checkin(db_session, checkin.id, current_user=liker)

    count = await like_service.count_checkin_likes(db_session, checkin.id)
    assert count == 0


async def test_unlike_list_raises_when_never_liked(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    other_user = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    with pytest.raises(LikeNotFoundError):
        await like_service.unlike_list(
            db_session, venue_list.id, current_user=other_user
        )


async def test_unlike_list_removes_the_like(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    liker = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    await set_current_user_identity(db_session, liker.id)
    await like_service.like_list(db_session, venue_list.id, current_user=liker)

    await like_service.unlike_list(db_session, venue_list.id, current_user=liker)

    count = await like_service.count_list_likes(db_session, venue_list.id)
    assert count == 0


async def test_like_list_raises_when_invisible_to_the_liker(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    stranger = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Özel", visibility=Visibility.PRIVATE
    )

    await set_current_user_identity(db_session, stranger.id)
    with pytest.raises(ListNotFoundError):
        await like_service.like_list(db_session, venue_list.id, current_user=stranger)


async def test_count_list_likes_counts_distinct_likers(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    liker_a = await _create_user(db_session)
    liker_b = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    await set_current_user_identity(db_session, liker_a.id)
    await like_service.like_list(db_session, venue_list.id, current_user=liker_a)
    await set_current_user_identity(db_session, liker_b.id)
    await like_service.like_list(db_session, venue_list.id, current_user=liker_b)
    await set_current_user_identity(db_session, liker_a.id)
    await like_service.like_list(db_session, venue_list.id, current_user=liker_a)

    count = await like_service.count_list_likes(db_session, venue_list.id)
    assert count == 2
