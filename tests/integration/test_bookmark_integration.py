"""Integration tests for app.services.bookmark against the real test
database — including the visibility-at-read-time behavior fixed during
adversarial testing: a bookmark must not outlive the visibility grant
that made it possible (see the module's own docstring).
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.visibility import Visibility
from app.exceptions import (
    BookmarkNotFoundError,
    CheckinNotFoundError,
    ListNotFoundError,
)
from app.models.list_bookmark import ListBookmark
from app.models.user import User
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import bookmark as bookmark_service
from app.services import checkin as checkin_service
from app.services import list as list_service

_CAFE_CATEGORY_ID = venue_category_id("cafe")
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


async def test_bookmark_checkin_is_idempotent(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)

    first = await bookmark_service.bookmark_checkin(
        db_session, checkin.id, current_user=bookmarker
    )
    second = await bookmark_service.bookmark_checkin(
        db_session, checkin.id, current_user=bookmarker
    )

    assert first.user_id == second.user_id


async def test_bookmark_checkin_raises_when_invisible(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner, visibility=Visibility.PRIVATE)

    with pytest.raises(CheckinNotFoundError):
        await bookmark_service.bookmark_checkin(
            db_session, checkin.id, current_user=stranger
        )


async def test_unbookmark_checkin_raises_when_never_bookmarked(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)

    with pytest.raises(BookmarkNotFoundError):
        await bookmark_service.unbookmark_checkin(
            db_session, checkin.id, current_user=other_user
        )


async def test_bookmarked_checkin_made_private_later_drops_out_of_the_list(
    db_session: AsyncSession,
) -> None:
    """Regression test for the existence-leak/stale-bookmark bug found
    during adversarial testing: bookmarking is visibility-gated at
    bookmark time, but *listing* bookmarks must re-check visibility at
    read time too, or a checkin made private after being bookmarked
    would still leak through the bookmarker's own bookmark list.
    """
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner, visibility=Visibility.PUBLIC)
    await bookmark_service.bookmark_checkin(
        db_session, checkin.id, current_user=bookmarker
    )

    await checkin_service.update_checkin(
        db_session,
        checkin.id,
        current_user=owner,
        updates={"visibility": Visibility.PRIVATE},
    )

    remaining = await bookmark_service.list_bookmarked_checkins(
        db_session, bookmarker.id, limit=20, offset=0
    )
    assert remaining == []


async def test_bookmarked_checkin_soft_deleted_later_drops_out_of_the_list(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)
    await bookmark_service.bookmark_checkin(
        db_session, checkin.id, current_user=bookmarker
    )

    await checkin_service.soft_delete_checkin(
        db_session, checkin.id, current_user=owner
    )

    remaining = await bookmark_service.list_bookmarked_checkins(
        db_session, bookmarker.id, limit=20, offset=0
    )
    assert remaining == []


async def test_owner_still_sees_their_own_bookmarked_private_checkin(
    db_session: AsyncSession,
) -> None:
    """The visibility re-check must not accidentally hide a bookmarker's
    own content from themselves.
    """
    owner = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner, visibility=Visibility.PRIVATE)
    await bookmark_service.bookmark_checkin(db_session, checkin.id, current_user=owner)

    remaining = await bookmark_service.list_bookmarked_checkins(
        db_session, owner.id, limit=20, offset=0
    )
    assert [c.id for c in remaining] == [checkin.id]


async def test_bookmark_list_raises_when_invisible(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Özel", visibility=Visibility.PRIVATE
    )

    with pytest.raises(ListNotFoundError):
        await bookmark_service.bookmark_list(
            db_session, venue_list.id, current_user=stranger
        )


async def test_bookmark_list_is_idempotent(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    first = await bookmark_service.bookmark_list(
        db_session, venue_list.id, current_user=bookmarker
    )
    second = await bookmark_service.bookmark_list(
        db_session, venue_list.id, current_user=bookmarker
    )

    assert first.user_id == second.user_id


async def test_unbookmark_list_raises_when_never_bookmarked(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    other_user = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )

    with pytest.raises(BookmarkNotFoundError):
        await bookmark_service.unbookmark_list(
            db_session, venue_list.id, current_user=other_user
        )


async def test_unbookmark_list_removes_it_from_the_bookmark_list(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    await bookmark_service.bookmark_list(
        db_session, venue_list.id, current_user=bookmarker
    )

    await bookmark_service.unbookmark_list(
        db_session, venue_list.id, current_user=bookmarker
    )

    remaining = await bookmark_service.list_bookmarked_lists(
        db_session, bookmarker.id, limit=20, offset=0
    )
    assert remaining == []


async def test_bookmarked_list_made_private_later_drops_out_of_the_list(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste", visibility=Visibility.PUBLIC
    )
    await bookmark_service.bookmark_list(
        db_session, venue_list.id, current_user=bookmarker
    )

    await list_service.update_list(
        db_session,
        venue_list.id,
        current_user=owner,
        updates={"visibility": Visibility.PRIVATE},
    )

    remaining = await bookmark_service.list_bookmarked_lists(
        db_session, bookmarker.id, limit=20, offset=0
    )
    assert remaining == []


async def test_list_bookmark_cascades_away_when_list_is_hard_deleted(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    bookmarker = await _create_user(db_session)
    venue_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Liste"
    )
    await bookmark_service.bookmark_list(
        db_session, venue_list.id, current_user=bookmarker
    )

    await list_service.delete_list(db_session, venue_list.id, current_user=owner)

    result = await db_session.execute(
        select(ListBookmark).where(ListBookmark.list_id == venue_list.id)
    )
    assert result.scalar_one_or_none() is None
