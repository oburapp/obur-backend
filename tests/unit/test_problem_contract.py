"""Unit tests for the RFC 9457 error contract.

The value of one body shape is that a client writes one parser, so these
tests check the shape on every kind of failure — including the ones FastAPI
and Starlette produce themselves, which have their own native formats.
"""

from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest_mock import MockerFixture

from app.core import problems
from app.core.auth import get_current_user
from app.core.problems import Problem, ProblemError
from app.exceptions import VenueNotFoundError
from app.main import app
from app.middleware.request_context import REQUEST_ID_HEADER
from app.models.user import User

_PROBLEM_MEDIA_TYPE = "application/problem+json"
_PUBLIC_ROUTE = "/api/v1/venue-categories"
_PROTECTED_ROUTE = "/api/v1/users/me"
_URN_PREFIX = "urn:obur:problem:"
_REQUIRED_MEMBERS = ("type", "title", "status")


@pytest.fixture
def _authenticated() -> Generator[None, None, None]:
    """Get past the auth dependency so validation is what fails."""
    app.dependency_overrides[get_current_user] = lambda: User(id=uuid4())
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def surfacing_client() -> AsyncGenerator[AsyncClient, None]:
    """A client that reads the 500 body instead of re-raising the exception.

    Starlette's `ServerErrorMiddleware` responds *and* re-raises, so the
    server can log a crash it did not expect. Under a real server that
    re-raise is caught by uvicorn; in-process it would reach the test, which
    is why the transport has to be told to leave it alone.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _problem(client: AsyncClient, method: str, path: str, **kwargs):
    response = await client.request(method, path, **kwargs)
    assert response.headers["content-type"].startswith(_PROBLEM_MEDIA_TYPE)
    return response


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        pytest.param("GET", "/api/v1/nope", 404, id="unrouted_path"),
        pytest.param("DELETE", _PUBLIC_ROUTE, 405, id="wrong_method"),
        pytest.param("GET", _PROTECTED_ROUTE, 401, id="unauthenticated"),
    ],
)
async def test_framework_errors_use_the_problem_shape(
    client: AsyncClient, method: str, path: str, expected_status: int
) -> None:
    """Starlette's own 404/405 and the auth dependency all render the same way."""
    response = await _problem(client, method, path)

    body = response.json()
    assert response.status_code == expected_status
    assert body["status"] == expected_status
    assert all(member in body for member in _REQUIRED_MEMBERS)


async def test_a_validation_failure_uses_the_problem_shape(
    client: AsyncClient, _authenticated: None
) -> None:
    """FastAPI's native `{"detail": [...]}` is normalised into the same body."""
    response = await _problem(client, "POST", "/api/v1/checkins", json={})

    assert response.json()["type"] == problems.VALIDATION_FAILED.type


async def test_a_validation_failure_reports_which_fields_failed(
    client: AsyncClient, _authenticated: None
) -> None:
    response = await _problem(client, "POST", "/api/v1/checkins", json={})

    assert response.json()["errors"]


async def test_a_domain_error_renders_its_declared_problem(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venues.venue_service.get_venue",
        AsyncMock(side_effect=VenueNotFoundError("gone")),
    )

    response = await _problem(client, "GET", f"/api/v1/venues/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["type"] == problems.VENUE_NOT_FOUND.type


async def test_a_domain_error_never_leaks_its_exception_message(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    """RFC 9457's security considerations: no implementation detail in a body."""
    secret = f"internal-{uuid4()}"
    mocker.patch(
        "app.api.v1.venues.venue_service.get_venue",
        AsyncMock(side_effect=VenueNotFoundError(secret)),
    )

    response = await _problem(client, "GET", f"/api/v1/venues/{uuid4()}")

    assert secret not in response.text


async def test_an_unexpected_error_returns_a_generic_problem(
    surfacing_client: AsyncClient, mocker: MockerFixture
) -> None:
    """Anything unmapped is a 500 whose body says nothing about the cause."""
    secret = f"boom-{uuid4()}"
    mocker.patch(
        "app.api.v1.venues.venue_service.get_venue",
        AsyncMock(side_effect=RuntimeError(secret)),
    )

    response = await _problem(surfacing_client, "GET", f"/api/v1/venues/{uuid4()}")

    assert response.status_code == 500
    assert secret not in response.text
    assert response.json()["type"] == problems.INTERNAL_ERROR.type


async def test_every_problem_response_carries_the_request_id(
    client: AsyncClient,
) -> None:
    """The id is what ties the body a caller saw to the line in the log."""
    response = await _problem(client, "GET", "/api/v1/nope")

    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


async def test_the_type_is_a_urn_rather_than_an_unresolvable_url() -> None:
    """ADR-0015: no production domain exists, and `type` values cannot change."""
    declared = [
        value for value in vars(problems).values() if isinstance(value, Problem)
    ]

    assert declared
    assert all(problem.type.startswith(_URN_PREFIX) for problem in declared)


async def test_every_declared_problem_has_a_written_detail() -> None:
    """`detail` is authored for a person; it is never derived from an exception."""
    declared = [
        value for value in vars(problems).values() if isinstance(value, Problem)
    ]

    assert all(problem.detail.strip() for problem in declared)


async def test_problem_types_are_unique() -> None:
    """`type` is the client's only discriminator, so two must never collide."""
    declared = [
        value for value in vars(problems).values() if isinstance(value, Problem)
    ]

    assert len({problem.type for problem in declared}) == len(declared)


async def test_an_explicitly_raised_problem_is_rendered(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "app.api.v1.venues.venue_service.get_venue",
        AsyncMock(side_effect=ProblemError(problems.ADMIN_REQUIRED)),
    )

    response = await _problem(client, "GET", f"/api/v1/venues/{uuid4()}")

    assert response.status_code == problems.ADMIN_REQUIRED.status
    assert response.json()["type"] == problems.ADMIN_REQUIRED.type


async def test_a_successful_response_is_not_problem_json(
    client: AsyncClient,
) -> None:
    response = await client.get(_PUBLIC_ROUTE)

    assert response.headers["content-type"].startswith("application/json")
    assert _PROBLEM_MEDIA_TYPE not in response.headers["content-type"]
