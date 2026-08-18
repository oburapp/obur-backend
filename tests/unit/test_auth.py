"""Tests for the get_current_user auth dependency."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pytest_mock import MockerFixture
from sqlalchemy.exc import IntegrityError

from app.core.auth import get_current_user, get_optional_current_user
from app.exceptions import InvalidTokenError
from app.models.user import User


def _session_returning(user: User | None) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()  # AsyncSession.add() is sync, not a coroutine
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session.execute.return_value = result
    return session


async def test_get_current_user_returns_existing_user(mocker: MockerFixture) -> None:
    existing = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")
    mocker.patch("app.core.auth.verify_session", AsyncMock(return_value="user_123"))
    session = _session_returning(existing)

    result = await get_current_user(MagicMock(), session)

    assert result is existing
    session.add.assert_not_called()


async def test_get_current_user_creates_user_jit_when_not_found(
    mocker: MockerFixture,
) -> None:
    mocker.patch("app.core.auth.verify_session", AsyncMock(return_value="user_new"))
    session = _session_returning(None)

    result = await get_current_user(MagicMock(), session)

    assert result.auth_provider == "clerk"
    assert result.auth_provider_id == "user_new"
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


async def test_get_current_user_resolves_race_on_integrity_error(
    mocker: MockerFixture,
) -> None:
    mocker.patch("app.core.auth.verify_session", AsyncMock(return_value="user_race"))
    winner = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_race")

    session = AsyncMock()
    session.add = MagicMock()
    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None
    second_result = MagicMock()
    second_result.scalar_one_or_none.return_value = winner
    session.execute.side_effect = [first_result, second_result]
    session.commit.side_effect = IntegrityError("stmt", {}, Exception("duplicate"))

    result = await get_current_user(MagicMock(), session)

    assert result is winner
    session.rollback.assert_awaited_once()


async def test_get_current_user_reraises_when_row_truly_missing_after_race(
    mocker: MockerFixture,
) -> None:
    """Defensive path: an IntegrityError implies the row exists, so if the
    re-query still can't find it, something else is wrong — propagate the
    original error rather than return a broken, unpersisted User.
    """
    mocker.patch("app.core.auth.verify_session", AsyncMock(return_value="user_ghost"))

    session = AsyncMock()
    session.add = MagicMock()
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    session.execute.side_effect = [empty_result, empty_result]
    session.commit.side_effect = IntegrityError("stmt", {}, Exception("duplicate"))

    with pytest.raises(IntegrityError):
        await get_current_user(MagicMock(), session)


async def test_get_current_user_raises_401_on_invalid_token(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "app.core.auth.verify_session",
        AsyncMock(side_effect=InvalidTokenError("bad token")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(MagicMock(), AsyncMock())

    assert exc_info.value.status_code == 401


async def test_get_optional_current_user_returns_none_on_invalid_token(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "app.core.auth.verify_session",
        AsyncMock(side_effect=InvalidTokenError("bad token")),
    )

    result = await get_optional_current_user(MagicMock(), AsyncMock())

    assert result is None


async def test_get_optional_current_user_returns_user_on_valid_token(
    mocker: MockerFixture,
) -> None:
    existing = User(id=uuid4(), auth_provider="clerk", auth_provider_id="user_123")
    mocker.patch("app.core.auth.verify_session", AsyncMock(return_value="user_123"))
    session = _session_returning(existing)

    result = await get_optional_current_user(MagicMock(), session)

    assert result is existing
