"""Unit tests for the seeder's entry point — the DB itself is mocked.

`seed_catalog`'s real SQL is exercised against a live database by the
integration fixture that seeds `obur_test` (tests/integration/conftest.py).
What's covered here is the wrapper the deploy step and `just seed` actually
invoke, which nothing else touches: if it stops disposing the engine or stops
calling the seeder, deploys break quietly.
"""

from unittest.mock import AsyncMock, MagicMock

from pytest_mock import MockerFixture

from app.seeds import runner


async def test_main_seeds_then_disposes_the_engine(mocker: MockerFixture) -> None:
    engine = AsyncMock()
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    mocker.patch("app.core.database.engine", engine)
    mocker.patch("app.core.database.async_session_factory", factory)
    seed = mocker.patch.object(runner, "seed_catalog", AsyncMock())

    await runner._main()

    seed.assert_awaited_once_with(session)
    engine.dispose.assert_awaited_once()


async def test_main_disposes_the_engine_even_when_seeding_fails(
    mocker: MockerFixture,
) -> None:
    """A half-seeded run must not also leak the connection pool — the deploy
    step should fail cleanly enough for the next attempt to start fresh.
    """
    engine = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = AsyncMock()
    mocker.patch("app.core.database.engine", engine)
    mocker.patch("app.core.database.async_session_factory", factory)
    mocker.patch.object(runner, "seed_catalog", AsyncMock(side_effect=RuntimeError))

    try:
        await runner._main()
    except RuntimeError:
        pass

    engine.dispose.assert_awaited_once()
