"""Tests for Clerk session token verification."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from app.core.security import verify_session
from app.exceptions import InvalidTokenError


def _request_state(
    *,
    is_signed_in: bool,
    payload: dict[str, str] | None = None,
    message: str | None = None,
) -> MagicMock:
    state = MagicMock()
    state.is_signed_in = is_signed_in
    state.payload = payload
    state.message = message
    return state


async def test_verify_session_returns_sub_when_signed_in(mocker: MockerFixture) -> None:
    state = _request_state(is_signed_in=True, payload={"sub": "user_123"})
    mocker.patch(
        "app.core.security.authenticate_request_async", AsyncMock(return_value=state)
    )

    result = await verify_session(MagicMock())

    assert result == "user_123"


async def test_verify_session_raises_when_not_signed_in(mocker: MockerFixture) -> None:
    state = _request_state(is_signed_in=False, message="token expired")
    mocker.patch(
        "app.core.security.authenticate_request_async", AsyncMock(return_value=state)
    )

    with pytest.raises(InvalidTokenError, match="token expired"):
        await verify_session(MagicMock())


async def test_verify_session_raises_when_payload_is_none(
    mocker: MockerFixture,
) -> None:
    state = _request_state(is_signed_in=True, payload=None)
    mocker.patch(
        "app.core.security.authenticate_request_async", AsyncMock(return_value=state)
    )

    with pytest.raises(InvalidTokenError):
        await verify_session(MagicMock())


async def test_verify_session_raises_when_sub_claim_is_missing(
    mocker: MockerFixture,
) -> None:
    state = _request_state(is_signed_in=True, payload={})
    mocker.patch(
        "app.core.security.authenticate_request_async", AsyncMock(return_value=state)
    )

    with pytest.raises(InvalidTokenError, match="sub"):
        await verify_session(MagicMock())
