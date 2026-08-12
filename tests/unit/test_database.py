"""Tests for the async session factory and database connectivity check."""

from unittest.mock import AsyncMock, MagicMock

from pytest_mock import MockerFixture
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import check_database_connection, get_session


def _make_connection_cm(*, raises: Exception | None = None) -> MagicMock:
    """Build a mock async context manager standing in for `engine.connect()`."""
    cm = MagicMock()
    if raises is not None:
        cm.__aenter__ = AsyncMock(side_effect=raises)
    else:
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


async def test_check_database_connection_returns_true_when_query_succeeds(
    mocker: MockerFixture,
) -> None:
    mock_engine = MagicMock()
    mock_engine.connect.return_value = _make_connection_cm()
    mocker.patch("app.core.database.engine", mock_engine)

    result = await check_database_connection()

    assert result is True


async def test_check_database_connection_returns_false_on_sqlalchemy_error(
    mocker: MockerFixture,
) -> None:
    mock_engine = MagicMock()
    mock_engine.connect.return_value = _make_connection_cm(
        raises=SQLAlchemyError("boom")
    )
    mocker.patch("app.core.database.engine", mock_engine)

    result = await check_database_connection()

    assert result is False


async def test_get_session_yields_a_session_from_the_factory(
    mocker: MockerFixture,
) -> None:
    mock_session = AsyncMock()
    factory_cm = MagicMock()
    factory_cm.__aenter__ = AsyncMock(return_value=mock_session)
    factory_cm.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("app.core.database.async_session_factory", return_value=factory_cm)

    sessions = [session async for session in get_session()]

    assert sessions == [mock_session]
