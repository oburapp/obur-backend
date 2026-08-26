"""Integration tests for migration 222227e6de3b: `close_friends_delete`,
`checkin_likes_delete`, `list_likes_delete`, `checkin_bookmarks_delete`,
and `list_bookmarks_delete` are now owner-only, not permissive on the
row's other party. That second branch was never reachable through any
shipped endpoint (see the migration's own docstring for the full audit),
so these tests prove the negative directly: a raw `DELETE` from the
*other* party now fails, while the actual owner's still succeeds, the
same "both directions" criterion `test_rls_policies_integration.py`'s
module docstring already sets.

`follows_delete` is deliberately not covered here: it keeps its second
branch, unchanged by this migration, because `DELETE
/api/v1/users/me/followers/{id}` is a real feature that needs it.
"""

from datetime import date
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.models.checkin import Checkin
from app.models.checkin_bookmark import CheckinBookmark
from app.models.checkin_like import CheckinLike
from app.models.close_friend import CloseFriend
from app.models.list_bookmark import ListBookmark
from app.models.list_like import ListLike
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import bookmark as bookmark_service
from app.services import checkin as checkin_service
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service
from app.services import like as like_service
from app.services import list as list_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
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
    await set_current_user_identity(session, added_by.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
        district="Kadıköy",
    )
    session.add(venue)
    await session.flush()
    return venue


async def _create_public_checkin(
    session: AsyncSession, owner: User, venue: Venue
) -> Checkin:
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
        visibility=Visibility.PUBLIC,
    )


async def test_close_friends_delete_rejects_the_friend_removing_themselves(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    friend = await _create_user(db_session)
    await set_current_user_identity(db_session, friend.id)
    await follow_service.follow_user(
        db_session, follower_id=friend.id, following_id=owner.id
    )
    await set_current_user_identity(db_session, owner.id)
    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=friend.id
    )

    await set_current_user_identity(db_session, friend.id)
    result = await db_session.execute(
        CloseFriend.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            CloseFriend.user_id == owner.id, CloseFriend.friend_id == friend.id
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]

    await set_current_user_identity(db_session, owner.id)
    result = await db_session.execute(
        CloseFriend.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            CloseFriend.user_id == owner.id, CloseFriend.friend_id == friend.id
        )
    )
    assert result.rowcount == 1  # pyright: ignore[reportAttributeAccessIssue]


async def test_checkin_likes_delete_rejects_the_checkin_owner_removing_a_like(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    liker = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await _create_public_checkin(db_session, owner, venue)
    await set_current_user_identity(db_session, liker.id)
    await like_service.like_checkin(db_session, checkin.id, current_user=liker)

    await set_current_user_identity(db_session, owner.id)
    result = await db_session.execute(
        CheckinLike.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            CheckinLike.checkin_id == checkin.id, CheckinLike.user_id == liker.id
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]

    await set_current_user_identity(db_session, liker.id)
    result = await db_session.execute(
        CheckinLike.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            CheckinLike.checkin_id == checkin.id, CheckinLike.user_id == liker.id
        )
    )
    assert result.rowcount == 1  # pyright: ignore[reportAttributeAccessIssue]


async def test_list_likes_delete_rejects_the_list_owner_removing_a_like(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    liker = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Kadıköy Gezisi"
    )
    await set_current_user_identity(db_session, liker.id)
    await like_service.like_list(db_session, venue_list.id, current_user=liker)

    await set_current_user_identity(db_session, owner.id)
    result = await db_session.execute(
        ListLike.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            ListLike.list_id == venue_list.id, ListLike.user_id == liker.id
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]

    await set_current_user_identity(db_session, liker.id)
    result = await db_session.execute(
        ListLike.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            ListLike.list_id == venue_list.id, ListLike.user_id == liker.id
        )
    )
    assert result.rowcount == 1  # pyright: ignore[reportAttributeAccessIssue]


async def test_checkin_bookmarks_delete_rejects_the_checkin_owner_removing_a_bookmark(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await _create_public_checkin(db_session, owner, venue)
    await set_current_user_identity(db_session, bookmarker.id)
    await bookmark_service.bookmark_checkin(
        db_session, checkin.id, current_user=bookmarker
    )

    await set_current_user_identity(db_session, owner.id)
    result = await db_session.execute(
        CheckinBookmark.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            CheckinBookmark.checkin_id == checkin.id,
            CheckinBookmark.user_id == bookmarker.id,
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]

    await set_current_user_identity(db_session, bookmarker.id)
    result = await db_session.execute(
        CheckinBookmark.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            CheckinBookmark.checkin_id == checkin.id,
            CheckinBookmark.user_id == bookmarker.id,
        )
    )
    assert result.rowcount == 1  # pyright: ignore[reportAttributeAccessIssue]


async def test_list_bookmarks_delete_rejects_the_list_owner_removing_a_bookmark(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Kadıköy Gezisi"
    )
    await set_current_user_identity(db_session, bookmarker.id)
    await bookmark_service.bookmark_list(
        db_session, venue_list.id, current_user=bookmarker
    )

    await set_current_user_identity(db_session, owner.id)
    result = await db_session.execute(
        ListBookmark.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            ListBookmark.list_id == venue_list.id,
            ListBookmark.user_id == bookmarker.id,
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]

    await set_current_user_identity(db_session, bookmarker.id)
    result = await db_session.execute(
        ListBookmark.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            ListBookmark.list_id == venue_list.id,
            ListBookmark.user_id == bookmarker.id,
        )
    )
    assert result.rowcount == 1  # pyright: ignore[reportAttributeAccessIssue]
