"""Integration tests for app.services.follow against the real test
database — self-follow's CHECK constraint and the composite primary key
both depend on real DB state.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import FollowNotFoundError, SelfFollowError
from app.models.user import User
from app.services import follow as follow_service


async def _create_user(session: AsyncSession) -> User:
    user = User(auth_provider="clerk", auth_provider_id=f"user_{uuid4()}")
    session.add(user)
    await session.flush()
    return user


async def test_follow_user_persists_and_appears_in_followers(
    db_session: AsyncSession,
) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)

    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=followee.id
    )

    followers = await follow_service.list_followers(
        db_session, followee.id, limit=20, offset=0
    )
    assert any(u.id == follower.id for u in followers)


async def test_follow_user_raises_for_self_follow(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)

    with pytest.raises(SelfFollowError):
        await follow_service.follow_user(
            db_session, follower_id=user.id, following_id=user.id
        )


async def test_follow_user_is_idempotent(db_session: AsyncSession) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)

    first = await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=followee.id
    )
    second = await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=followee.id
    )

    assert first.created_at == second.created_at


async def test_unfollow_user_removes_the_relationship(db_session: AsyncSession) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=followee.id
    )

    await follow_service.unfollow_user(
        db_session, follower_id=follower.id, following_id=followee.id
    )

    followers = await follow_service.list_followers(
        db_session, followee.id, limit=20, offset=0
    )
    assert followers == []


async def test_unfollow_user_raises_when_not_following(
    db_session: AsyncSession,
) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)

    with pytest.raises(FollowNotFoundError):
        await follow_service.unfollow_user(
            db_session, follower_id=follower.id, following_id=followee.id
        )


async def test_remove_follower_removes_the_same_relationship_as_unfollow(
    db_session: AsyncSession,
) -> None:
    follower = await _create_user(db_session)
    followee = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=followee.id
    )

    await follow_service.remove_follower(
        db_session, user_id=followee.id, follower_id=follower.id
    )

    following = await follow_service.list_following(
        db_session, follower.id, limit=20, offset=0
    )
    assert following == []


async def test_remove_follower_raises_when_not_actually_a_follower(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    non_follower = await _create_user(db_session)

    with pytest.raises(FollowNotFoundError):
        await follow_service.remove_follower(
            db_session, user_id=user.id, follower_id=non_follower.id
        )


async def test_list_following_returns_who_a_user_follows(
    db_session: AsyncSession,
) -> None:
    follower = await _create_user(db_session)
    followee_a = await _create_user(db_session)
    followee_b = await _create_user(db_session)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=followee_a.id
    )
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=followee_b.id
    )

    following = await follow_service.list_following(
        db_session, follower.id, limit=20, offset=0
    )

    assert {u.id for u in following} == {followee_a.id, followee_b.id}
