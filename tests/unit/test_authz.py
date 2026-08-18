"""Unit tests for app.core.authz."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.authz import (
    can_view,
    close_friend_of_owner_exists,
    ensure_visible_and_owned,
    is_close_friend,
    is_owner_or_admin,
    require_admin,
)
from app.core.visibility import Visibility
from app.exceptions import CheckinNotFoundError, NotCheckinOwnerError
from app.models.checkin import Checkin
from app.models.user import User, UserRole


def _user(role: str = UserRole.USER) -> User:
    return User(id=uuid4(), auth_provider="clerk", auth_provider_id="x", role=role)


def test_is_owner_or_admin_true_for_the_owner() -> None:
    user = _user()

    assert is_owner_or_admin(user.id, user) is True


def test_is_owner_or_admin_true_for_an_admin_acting_on_someone_elses_resource() -> None:
    admin = _user(role=UserRole.ADMIN)

    assert is_owner_or_admin(uuid4(), admin) is True


def test_is_owner_or_admin_false_for_a_regular_user_on_someone_elses_resource() -> None:
    user = _user()

    assert is_owner_or_admin(uuid4(), user) is False


async def test_require_admin_returns_the_user_when_admin() -> None:
    admin = _user(role=UserRole.ADMIN)

    result = await require_admin(admin)

    assert result is admin


async def test_require_admin_raises_403_for_a_regular_user() -> None:
    user = _user()

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(user)

    assert exc_info.value.status_code == 403


def _session_with_close_friend_result(*, found: bool) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = MagicMock() if found else None
    session.execute.return_value = result
    return session


async def test_is_close_friend_true_when_a_row_exists() -> None:
    session = _session_with_close_friend_result(found=True)

    assert await is_close_friend(session, owner_id=uuid4(), viewer_id=uuid4()) is True


async def test_is_close_friend_false_when_no_row_exists() -> None:
    session = _session_with_close_friend_result(found=False)

    assert await is_close_friend(session, owner_id=uuid4(), viewer_id=uuid4()) is False


async def test_can_view_true_for_the_owner_regardless_of_visibility() -> None:
    owner = _user()
    session = AsyncMock()

    result = await can_view(
        session, owner_id=owner.id, visibility=Visibility.PRIVATE, viewer=owner
    )

    assert result is True


async def test_can_view_true_for_an_admin_regardless_of_visibility() -> None:
    admin = _user(role=UserRole.ADMIN)
    session = AsyncMock()

    result = await can_view(
        session, owner_id=uuid4(), visibility=Visibility.PRIVATE, viewer=admin
    )

    assert result is True


async def test_can_view_true_for_public_with_no_viewer() -> None:
    session = AsyncMock()

    result = await can_view(
        session, owner_id=uuid4(), visibility=Visibility.PUBLIC, viewer=None
    )

    assert result is True


async def test_can_view_false_for_private_with_no_viewer() -> None:
    session = AsyncMock()

    result = await can_view(
        session, owner_id=uuid4(), visibility=Visibility.PRIVATE, viewer=None
    )

    assert result is False


async def test_can_view_false_for_private_with_a_stranger_viewer() -> None:
    session = AsyncMock()

    result = await can_view(
        session, owner_id=uuid4(), visibility=Visibility.PRIVATE, viewer=_user()
    )

    assert result is False


async def test_can_view_false_for_close_friends_with_no_viewer() -> None:
    session = AsyncMock()

    result = await can_view(
        session, owner_id=uuid4(), visibility=Visibility.CLOSE_FRIENDS, viewer=None
    )

    assert result is False


async def test_can_view_true_for_close_friends_when_viewer_is_a_close_friend() -> None:
    session = _session_with_close_friend_result(found=True)

    result = await can_view(
        session,
        owner_id=uuid4(),
        visibility=Visibility.CLOSE_FRIENDS,
        viewer=_user(),
    )

    assert result is True


async def test_can_view_false_for_close_friends_when_viewer_is_not_a_close_friend() -> (
    None
):
    session = _session_with_close_friend_result(found=False)

    result = await can_view(
        session,
        owner_id=uuid4(),
        visibility=Visibility.CLOSE_FRIENDS,
        viewer=_user(),
    )

    assert result is False


async def test_can_view_false_for_an_unrecognized_visibility_value() -> None:
    """Defense in depth: `visibility` is constrained to the three known
    tiers by a DB CHECK constraint, but `can_view` itself must still
    fail closed (deny, not crash) if it ever sees anything else.
    """
    session = AsyncMock()

    result = await can_view(
        session, owner_id=uuid4(), visibility="not_a_real_tier", viewer=_user()
    )

    assert result is False


async def test_ensure_visible_and_owned_returns_silently_for_the_owner() -> None:
    owner = _user()
    session = AsyncMock()

    await ensure_visible_and_owned(
        session,
        owner_id=owner.id,
        visibility=Visibility.PRIVATE,
        current_user=owner,
        not_found_error=CheckinNotFoundError,
        not_found_message="nope",
        not_owner_error=NotCheckinOwnerError,
        not_owner_message="nope",
    )


async def test_ensure_visible_and_owned_raises_not_found_when_invisible() -> None:
    session = AsyncMock()

    with pytest.raises(CheckinNotFoundError):
        await ensure_visible_and_owned(
            session,
            owner_id=uuid4(),
            visibility=Visibility.PRIVATE,
            current_user=_user(),
            not_found_error=CheckinNotFoundError,
            not_found_message="not found",
            not_owner_error=NotCheckinOwnerError,
            not_owner_message="not owner",
        )


async def test_ensure_visible_and_owned_raises_not_owner_when_visible() -> None:
    """A stranger acting on PUBLIC content they don't own gets the
    ordinary 403 — the existence-leak guard must not swallow this case.
    """
    session = AsyncMock()

    with pytest.raises(NotCheckinOwnerError):
        await ensure_visible_and_owned(
            session,
            owner_id=uuid4(),
            visibility=Visibility.PUBLIC,
            current_user=_user(),
            not_found_error=CheckinNotFoundError,
            not_found_message="not found",
            not_owner_error=NotCheckinOwnerError,
            not_owner_message="not owner",
        )


def test_close_friend_of_owner_exists_builds_a_correlated_exists_clause() -> None:
    clause = close_friend_of_owner_exists(Checkin.user_id, uuid4())

    assert "EXISTS" in str(clause).upper()
