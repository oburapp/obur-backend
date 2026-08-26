"""Integration tests for app.services.block against the real test
database. Idempotency and the self-block CHECK both depend on real DB
state; the retroactive purge depends on the real
`rls_purge_interactions_between` SECURITY DEFINER function (migration
619903be1de5), which a mocked session couldn't meaningfully exercise.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import BlockNotFoundError, SelfBlockError
from app.models.checkin import Checkin
from app.models.checkin_bookmark import CheckinBookmark
from app.models.checkin_like import CheckinLike
from app.models.follow import Follow
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import block as block_service
from app.services import bookmark as bookmark_service
from app.services import checkin as checkin_service
from app.services import follow as follow_service
from app.services import like as like_service

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


async def _create_public_checkin(session: AsyncSession, owner: User) -> Checkin:
    await set_current_user_identity(session, owner.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
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
        visibility=Visibility.PUBLIC,
    )


async def test_create_block_persists_and_appears_in_list_blocked_users(
    db_session: AsyncSession,
) -> None:
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await set_current_user_identity(db_session, blocker.id)

    await block_service.create_block(
        db_session, blocker_id=blocker.id, blocked_id=blocked.id
    )

    blocked_users = await block_service.list_blocked_users(
        db_session, limit=20, offset=0
    )
    assert any(u.id == blocked.id for u in blocked_users)


async def test_create_block_raises_for_self_block(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)

    with pytest.raises(SelfBlockError):
        await block_service.create_block(
            db_session, blocker_id=user.id, blocked_id=user.id
        )


async def test_create_block_is_idempotent(db_session: AsyncSession) -> None:
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await set_current_user_identity(db_session, blocker.id)

    first = await block_service.create_block(
        db_session, blocker_id=blocker.id, blocked_id=blocked.id
    )
    second = await block_service.create_block(
        db_session, blocker_id=blocker.id, blocked_id=blocked.id
    )

    assert first.created_at == second.created_at


async def test_remove_block_removes_the_relationship(db_session: AsyncSession) -> None:
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await set_current_user_identity(db_session, blocker.id)
    await block_service.create_block(
        db_session, blocker_id=blocker.id, blocked_id=blocked.id
    )

    await block_service.remove_block(
        db_session, blocker_id=blocker.id, blocked_id=blocked.id
    )

    blocked_users = await block_service.list_blocked_users(
        db_session, limit=20, offset=0
    )
    assert blocked_users == []


async def test_remove_block_raises_when_not_blocked(db_session: AsyncSession) -> None:
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await set_current_user_identity(db_session, blocker.id)

    with pytest.raises(BlockNotFoundError):
        await block_service.remove_block(
            db_session, blocker_id=blocker.id, blocked_id=blocked.id
        )


async def test_list_blocked_users_only_ever_returns_the_current_sessions_own_list(
    db_session: AsyncSession,
) -> None:
    """`rls_list_blocked_users` is a real RLS bypass with no
    caller-supplied id to get wrong (see migration `f1d017015e34`): it
    reads `rls_current_user_id()` itself. Proven here with two blockers,
    each with their own blocked user, switching identity between them,
    the same session and function call must never blend the two lists.
    """
    blocker_a = await _create_user(db_session)
    blocked_by_a = await _create_user(db_session)
    blocker_b = await _create_user(db_session)
    blocked_by_b = await _create_user(db_session)

    await set_current_user_identity(db_session, blocker_a.id)
    await block_service.create_block(
        db_session, blocker_id=blocker_a.id, blocked_id=blocked_by_a.id
    )
    await set_current_user_identity(db_session, blocker_b.id)
    await block_service.create_block(
        db_session, blocker_id=blocker_b.id, blocked_id=blocked_by_b.id
    )

    await set_current_user_identity(db_session, blocker_a.id)
    a_sees = await block_service.list_blocked_users(db_session, limit=20, offset=0)
    assert {u.id for u in a_sees} == {blocked_by_a.id}

    await set_current_user_identity(db_session, blocker_b.id)
    b_sees = await block_service.list_blocked_users(db_session, limit=20, offset=0)
    assert {u.id for u in b_sees} == {blocked_by_b.id}


async def test_create_block_auto_unfollows_both_directions(
    db_session: AsyncSession,
) -> None:
    a = await _create_user(db_session)
    b = await _create_user(db_session)
    await set_current_user_identity(db_session, a.id)
    await follow_service.follow_user(db_session, follower_id=a.id, following_id=b.id)
    await set_current_user_identity(db_session, b.id)
    await follow_service.follow_user(db_session, follower_id=b.id, following_id=a.id)

    await set_current_user_identity(db_session, a.id)
    await block_service.create_block(db_session, blocker_id=a.id, blocked_id=b.id)

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    remaining_follows = (
        (
            await db_session.execute(
                select(Follow).where(
                    Follow.follower_id.in_([a.id, b.id]),
                    Follow.following_id.in_([a.id, b.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining_follows == []


async def test_create_block_purges_interactions_in_both_directions_only(
    db_session: AsyncSession,
) -> None:
    """The full retroactive-purge scenario (PDD §11): A's like and
    bookmark of B's checkin, B's like of A's checkin, and the
    notifications either one triggered on the other, are all gone once
    A blocks B. A third, unrelated user's like on A's checkin is
    untouched, the purge must not over-reach past the blocked pair.
    """
    a = await _create_user(db_session)
    b = await _create_user(db_session)
    stranger = await _create_user(db_session)

    a_checkin = await _create_public_checkin(db_session, a)
    b_checkin = await _create_public_checkin(db_session, b)

    await set_current_user_identity(db_session, b.id)
    await like_service.like_checkin(db_session, a_checkin.id, current_user=b)
    await bookmark_service.bookmark_checkin(db_session, a_checkin.id, current_user=b)

    await set_current_user_identity(db_session, a.id)
    await like_service.like_checkin(db_session, b_checkin.id, current_user=a)

    await set_current_user_identity(db_session, stranger.id)
    await like_service.like_checkin(db_session, a_checkin.id, current_user=stranger)

    await set_current_user_identity(db_session, a.id)
    await block_service.create_block(db_session, blocker_id=a.id, blocked_id=b.id)

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)

    remaining_likes = (
        (
            await db_session.execute(
                select(CheckinLike).where(
                    CheckinLike.checkin_id.in_([a_checkin.id, b_checkin.id])
                )
            )
        )
        .scalars()
        .all()
    )
    assert {like.user_id for like in remaining_likes} == {stranger.id}

    remaining_bookmarks = (
        (
            await db_session.execute(
                select(CheckinBookmark).where(
                    CheckinBookmark.checkin_id == a_checkin.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining_bookmarks == []

    remaining_notifications = (
        (
            await db_session.execute(
                select(Notification).where(
                    Notification.user_id.in_([a.id, b.id]),
                    Notification.actor_id.in_([a.id, b.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining_notifications == []
