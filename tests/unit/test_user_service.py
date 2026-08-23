"""Unit tests for app.services.user — every DB call is mocked."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.exceptions import (
    AccountNotFrozenError,
    UsernameChangedTooRecentlyError,
    UsernameTakenError,
)
from app.models.user import User, UserRole, UserStatus
from app.services import user as user_service

_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "auth_provider": "clerk",
        "auth_provider_id": "x",
        "username": "erenm",
        "display_name": "Eren",
        "status": UserStatus.ACTIVE,
        "role": UserRole.USER,
        "username_changed_at": None,
    }
    defaults.update(overrides)
    return User(**defaults)


def _session(*, username_owner_id: object = None) -> AsyncMock:
    """A session whose only query answers "who currently holds this handle?"."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = username_owner_id
    session.execute.return_value = result
    return session


async def test_update_profile_applies_editable_fields() -> None:
    user = _user()

    updated = await user_service.update_profile(
        _session(), user=user, changes={"display_name": "Eren M", "bio": "merhaba"}
    )

    assert updated.display_name == "Eren M"
    assert updated.bio == "merhaba"


async def test_update_profile_ignores_role_and_status() -> None:
    """Neither is settable through any user-facing path (PDD §7, §11). The
    request schema omits them; this is the second line of defence.
    """
    user = _user()

    updated = await user_service.update_profile(
        _session(),
        user=user,
        changes={"role": UserRole.ADMIN, "status": UserStatus.SUSPENDED},
    )

    assert updated.role == UserRole.USER
    assert updated.status == UserStatus.ACTIVE


async def test_update_profile_leaves_unmentioned_fields_alone() -> None:
    user = _user(bio="eski")

    updated = await user_service.update_profile(
        _session(), user=user, changes={"display_name": "Yeni"}
    )

    assert updated.bio == "eski"


async def test_update_profile_sets_changed_at_on_first_username_change() -> None:
    user = _user(username_changed_at=None)

    updated = await user_service.update_profile(
        _session(), user=user, changes={"username": "yeniad"}, now=_NOW
    )

    assert updated.username == "yeniad"
    assert updated.username_changed_at == _NOW


async def test_update_profile_rejects_a_username_someone_else_holds() -> None:
    user = _user()

    with pytest.raises(UsernameTakenError):
        await user_service.update_profile(
            _session(username_owner_id=uuid4()),
            user=user,
            changes={"username": "alinmis"},
            now=_NOW,
        )


async def test_update_profile_rejects_a_username_change_inside_the_window() -> None:
    changed_at = _NOW - timedelta(days=user_service.USERNAME_CHANGE_INTERVAL_DAYS - 1)
    user = _user(username_changed_at=changed_at)

    with pytest.raises(UsernameChangedTooRecentlyError):
        await user_service.update_profile(
            _session(), user=user, changes={"username": "yeniad"}, now=_NOW
        )


async def test_update_profile_allows_a_username_change_after_the_window() -> None:
    changed_at = _NOW - timedelta(days=user_service.USERNAME_CHANGE_INTERVAL_DAYS + 1)
    user = _user(username_changed_at=changed_at)

    updated = await user_service.update_profile(
        _session(), user=user, changes={"username": "yeniad"}, now=_NOW
    )

    assert updated.username == "yeniad"
    assert updated.username_changed_at == _NOW


async def test_update_profile_does_not_rate_limit_resubmitting_the_same_username() -> (
    None
):
    """A client sending the whole profile back unchanged must not burn the
    user's one allowed change on a handle that didn't move.
    """
    changed_at = _NOW - timedelta(days=1)
    user = _user(username="erenm", username_changed_at=changed_at)

    updated = await user_service.update_profile(
        _session(), user=user, changes={"username": "erenm"}, now=_NOW
    )

    assert updated.username_changed_at == changed_at


async def test_freeze_account_freezes_an_active_account() -> None:
    session = AsyncMock()
    user = _user(status=UserStatus.ACTIVE)

    frozen = await user_service.freeze_account(session, user=user)

    assert frozen.status == UserStatus.FROZEN
    session.commit.assert_awaited_once()


async def test_freeze_account_is_idempotent() -> None:
    session = AsyncMock()
    user = _user(status=UserStatus.FROZEN)

    await user_service.freeze_account(session, user=user)

    session.commit.assert_not_awaited()


async def test_freeze_account_leaves_a_suspended_account_suspended() -> None:
    """Otherwise a suspended user could convert an admin action into one
    they can undo by signing back in.
    """
    session = AsyncMock()
    user = _user(status=UserStatus.SUSPENDED)

    result = await user_service.freeze_account(session, user=user)

    assert result.status == UserStatus.SUSPENDED
    session.commit.assert_not_awaited()


async def test_reactivate_account_unfreezes() -> None:
    session = AsyncMock()
    user = _user(status=UserStatus.FROZEN)

    reactivated = await user_service.reactivate_account(session, user=user)

    assert reactivated.status == UserStatus.ACTIVE


async def test_reactivate_account_is_a_no_op_when_already_active() -> None:
    session = AsyncMock()
    user = _user(status=UserStatus.ACTIVE)

    await user_service.reactivate_account(session, user=user)

    session.commit.assert_not_awaited()


async def test_reactivate_account_refuses_a_suspended_account() -> None:
    user = _user(status=UserStatus.SUSPENDED)

    with pytest.raises(AccountNotFrozenError):
        await user_service.reactivate_account(AsyncMock(), user=user)


async def test_delete_account_issues_a_delete_and_commits() -> None:
    session = AsyncMock()

    await user_service.delete_account(session, user_id=uuid4())

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
