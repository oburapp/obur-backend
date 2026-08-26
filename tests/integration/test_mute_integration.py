"""Integration tests for app.services.mute against the real test
database: idempotency and the self-mute CHECK both depend on real DB
state.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.exceptions import MuteNotFoundError, SelfMuteError
from app.models.user import User
from app.services import mute as mute_service


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


async def test_create_mute_persists_and_appears_in_list_muted_users(
    db_session: AsyncSession,
) -> None:
    muter = await _create_user(db_session)
    muted = await _create_user(db_session)
    await set_current_user_identity(db_session, muter.id)

    await mute_service.create_mute(db_session, user_id=muter.id, muted_id=muted.id)

    muted_users = await mute_service.list_muted_users(
        db_session, muter.id, limit=20, offset=0
    )
    assert any(u.id == muted.id for u in muted_users)


async def test_create_mute_raises_for_self_mute(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    await set_current_user_identity(db_session, user.id)

    with pytest.raises(SelfMuteError):
        await mute_service.create_mute(db_session, user_id=user.id, muted_id=user.id)


async def test_create_mute_is_idempotent(db_session: AsyncSession) -> None:
    muter = await _create_user(db_session)
    muted = await _create_user(db_session)
    await set_current_user_identity(db_session, muter.id)

    first = await mute_service.create_mute(
        db_session, user_id=muter.id, muted_id=muted.id
    )
    second = await mute_service.create_mute(
        db_session, user_id=muter.id, muted_id=muted.id
    )

    assert first.created_at == second.created_at


async def test_remove_mute_removes_the_relationship(db_session: AsyncSession) -> None:
    muter = await _create_user(db_session)
    muted = await _create_user(db_session)
    await set_current_user_identity(db_session, muter.id)
    await mute_service.create_mute(db_session, user_id=muter.id, muted_id=muted.id)

    await mute_service.remove_mute(db_session, user_id=muter.id, muted_id=muted.id)

    muted_users = await mute_service.list_muted_users(
        db_session, muter.id, limit=20, offset=0
    )
    assert muted_users == []


async def test_remove_mute_raises_when_not_muted(db_session: AsyncSession) -> None:
    muter = await _create_user(db_session)
    muted = await _create_user(db_session)
    await set_current_user_identity(db_session, muter.id)

    with pytest.raises(MuteNotFoundError):
        await mute_service.remove_mute(db_session, user_id=muter.id, muted_id=muted.id)
