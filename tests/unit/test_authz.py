"""Unit tests for app.core.authz."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.authz import is_owner_or_admin, require_admin
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
