"""Integration tests for app.services.close_friend against the real test
database — the composite foreign key to `follows` (must-currently-follow,
cascade-on-unfollow) only actually gets exercised against a real DB.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CloseFriendNotFoundError, NotAFollowerError
from app.models.user import User
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service


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


async def test_add_close_friend_raises_when_not_currently_a_follower(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    non_follower = await _create_user(db_session)

    with pytest.raises(NotAFollowerError):
        await close_friend_service.add_close_friend(
            db_session, user_id=owner.id, friend_id=non_follower.id
        )


async def test_add_close_friend_succeeds_for_a_current_follower(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    follower = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=owner.id
    )

    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=follower.id
    )

    friends = await close_friend_service.list_close_friends(
        db_session, owner.id, limit=20, offset=0
    )
    assert any(u.id == follower.id for u in friends)


async def test_add_close_friend_is_idempotent(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    follower = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=owner.id
    )

    first = await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=follower.id
    )
    second = await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=follower.id
    )

    assert first.created_at == second.created_at


async def test_remove_close_friend_raises_when_not_on_the_list(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)

    with pytest.raises(CloseFriendNotFoundError):
        await close_friend_service.remove_close_friend(
            db_session, user_id=owner.id, friend_id=stranger.id
        )


async def test_remove_close_friend_removes_the_relationship(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    follower = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=owner.id
    )
    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=follower.id
    )

    await close_friend_service.remove_close_friend(
        db_session, user_id=owner.id, friend_id=follower.id
    )

    friends = await close_friend_service.list_close_friends(
        db_session, owner.id, limit=20, offset=0
    )
    assert friends == []


async def test_unfollow_cascades_removal_from_close_friends(
    db_session: AsyncSession,
) -> None:
    """The composite FK's `ON DELETE CASCADE` (see
    app/models/close_friend.py) must remove the close-friend row the
    moment the underlying follow is deleted — a close friend can never
    outlive the follow relationship it was built on.
    """
    owner = await _create_user(db_session)
    follower = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=owner.id
    )
    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=follower.id
    )

    await follow_service.unfollow_user(
        db_session, follower_id=follower.id, following_id=owner.id
    )

    friends = await close_friend_service.list_close_friends(
        db_session, owner.id, limit=20, offset=0
    )
    assert friends == []


async def test_close_friend_status_is_not_symmetric(db_session: AsyncSession) -> None:
    """`owner` adding `follower` as a close friend says nothing about
    whether `owner` is `follower`'s close friend too — it's a one-way,
    manually curated relationship in each direction independently.
    """
    owner = await _create_user(db_session)
    follower = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=owner.id
    )
    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=follower.id
    )

    reverse_direction = await close_friend_service.list_close_friends(
        db_session, follower.id, limit=20, offset=0
    )
    assert reverse_direction == []
