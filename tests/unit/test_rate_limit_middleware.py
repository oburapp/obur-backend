"""Unit tests for the rate limiter.

The counters run against the real test Redis (db 1), because the property
worth testing is that repeated requests actually accumulate — a mocked store
would only test that the middleware calls it. Counters are cleared between
tests by the autouse fixture in conftest.py.
"""

import re
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pytest_mock import MockerFixture
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core import problems
from app.middleware.rate_limit import (
    BASELINE_LIMIT,
    KEY_NAMESPACE,
    STRICT_LIMIT,
    STRICT_ROUTES,
    WINDOW_SECONDS,
)

_PUBLIC_ROUTE = "/api/v1/venue-categories"
_STRICT_ROUTE = "/api/v1/checkins"
_TRUE_CLIENT = "203.0.113.7"
_HEALTH_ROUTE = "/health"
_PATH_PARAMETER = re.compile(r"\{[^/}]+\}")


@pytest.fixture
def _behind_one_proxy(mocker: MockerFixture) -> None:
    """Read the client address from X-Forwarded-For, as in deployment."""
    mocker.patch(
        "app.core.client_ip.get_settings",
        return_value=MagicMock(trusted_proxy_count=1),
    )


@pytest.fixture
def _at_the_limit(mocker: MockerFixture) -> Callable[[int, int], None]:
    """Make the store report a count without issuing that many requests."""

    def _set(count: int, ttl: int) -> None:
        mocker.patch(
            "app.middleware.rate_limit.redis_client.eval",
            AsyncMock(return_value=[count, ttl]),
        )

    return _set


async def test_a_request_under_the_limit_is_served(client: AsyncClient) -> None:
    response = await client.get(_PUBLIC_ROUTE)

    assert response.status_code == 200


async def test_the_response_advertises_the_remaining_quota(
    client: AsyncClient,
) -> None:
    response = await client.get(_PUBLIC_ROUTE)

    assert response.headers["RateLimit-Limit"] == str(BASELINE_LIMIT)
    assert response.headers["RateLimit-Remaining"] == str(BASELINE_LIMIT - 1)
    assert int(response.headers["RateLimit-Reset"]) <= WINDOW_SECONDS


async def test_remaining_decreases_across_requests(client: AsyncClient) -> None:
    """The counter accumulates rather than being reset per request."""
    first = await client.get(_PUBLIC_ROUTE)
    second = await client.get(_PUBLIC_ROUTE)

    assert (
        int(second.headers["RateLimit-Remaining"])
        == int(first.headers["RateLimit-Remaining"]) - 1
    )


async def test_a_request_over_the_limit_is_refused(
    client: AsyncClient, _at_the_limit: Callable[[int, int], None]
) -> None:
    _at_the_limit(BASELINE_LIMIT + 1, WINDOW_SECONDS)

    response = await client.get(_PUBLIC_ROUTE)

    assert response.status_code == 429
    assert response.json()["type"] == problems.RATE_LIMITED.type


def _refusal_headers(response) -> dict[str, str]:
    return {name: response.headers[name] for name in ("Retry-After", "RateLimit-Reset")}


async def test_a_refusal_tells_the_caller_when_to_retry(
    client: AsyncClient, _at_the_limit: Callable[[int, int], None]
) -> None:
    _at_the_limit(BASELINE_LIMIT + 1, 42)

    response = await client.get(_PUBLIC_ROUTE)

    assert _refusal_headers(response) == {"Retry-After": "42", "RateLimit-Reset": "42"}
    assert response.headers["RateLimit-Remaining"] == "0"


async def test_a_refusal_never_advertises_a_zero_second_retry(
    client: AsyncClient, _at_the_limit: Callable[[int, int], None]
) -> None:
    """Redis reports -1/-2 for a key with no TTL; retrying instantly is useless."""
    _at_the_limit(BASELINE_LIMIT + 1, -2)

    response = await client.get(_PUBLIC_ROUTE)

    assert int(response.headers["Retry-After"]) >= 1


async def test_a_spoofed_forwarded_for_prefix_shares_one_counter(
    client: AsyncClient, _behind_one_proxy: None
) -> None:
    """The bypass this design exists to prevent.

    Every request below claims a different originating address. Only the
    rightmost entry — the one our own proxy appended — is trusted, so all of
    them must land in the same counter and the quota must keep falling.
    """
    remaining: list[int] = []
    for spoofed in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        response = await client.get(
            _PUBLIC_ROUTE,
            headers={"X-Forwarded-For": f"{spoofed}, {_TRUE_CLIENT}"},
        )
        remaining.append(int(response.headers["RateLimit-Remaining"]))

    assert remaining == [BASELINE_LIMIT - 1, BASELINE_LIMIT - 2, BASELINE_LIMIT - 3]


async def test_different_clients_get_separate_counters(
    client: AsyncClient, _behind_one_proxy: None
) -> None:
    """The counterpart: a genuinely different address must not inherit a quota."""
    await client.get(_PUBLIC_ROUTE, headers={"X-Forwarded-For": _TRUE_CLIENT})
    other = await client.get(_PUBLIC_ROUTE, headers={"X-Forwarded-For": "198.51.100.4"})

    assert int(other.headers["RateLimit-Remaining"]) == BASELINE_LIMIT - 1


async def test_write_routes_use_the_strict_tier(client: AsyncClient) -> None:
    """Unauthenticated, so this stops at auth — the tier is chosen before that."""
    response = await client.post(_STRICT_ROUTE, json={})

    assert response.headers["RateLimit-Limit"] == str(STRICT_LIMIT)


async def test_reads_keep_working_when_the_store_is_unavailable(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    """Fail open: browsing must not depend on infrastructure with no HA."""
    mocker.patch(
        "app.middleware.rate_limit.redis_client.eval",
        AsyncMock(side_effect=RedisConnectionError("down")),
    )

    response = await client.get(_PUBLIC_ROUTE)

    assert response.status_code == 200


async def test_writes_are_refused_when_the_store_is_unavailable(
    client: AsyncClient, mocker: MockerFixture
) -> None:
    """Fail closed: an unmetered write path is the rating-manipulation route."""
    mocker.patch(
        "app.middleware.rate_limit.redis_client.eval",
        AsyncMock(side_effect=RedisConnectionError("down")),
    )

    response = await client.post(_STRICT_ROUTE, json={})

    assert response.status_code == 503
    assert response.json()["type"] == problems.RATE_LIMITER_UNAVAILABLE.type


async def test_the_counter_always_receives_an_expiry(client: AsyncClient) -> None:
    """A counter incremented without a TTL locks its caller out permanently.

    This is why the increment and the expiry are one Lua call rather than
    two round trips (ADR-0014).
    """
    from app.core.redis import redis_client

    await client.get(_PUBLIC_ROUTE)

    keys = [key async for key in redis_client.scan_iter(match=f"{KEY_NAMESPACE}:*")]
    assert keys
    for key in keys:
        assert await redis_client.ttl(key) > 0


async def test_an_unresolvable_address_is_counted_rather_than_exempted(
    client: AsyncClient, _behind_one_proxy: None
) -> None:
    """No address is not a free pass; it is its own bucket."""
    first = await client.get(_PUBLIC_ROUTE, headers={"X-Forwarded-For": "garbage"})
    second = await client.get(_PUBLIC_ROUTE, headers={"X-Forwarded-For": "garbage"})

    assert (
        int(second.headers["RateLimit-Remaining"])
        == int(first.headers["RateLimit-Remaining"]) - 1
    )


async def test_operational_endpoints_are_limited_too(client: AsyncClient) -> None:
    """Nothing is exempt; /health is reachable without authentication."""
    response = await client.get(_HEALTH_ROUTE)

    assert "RateLimit-Limit" in response.headers


@pytest.mark.parametrize(("method", "template"), sorted(STRICT_ROUTES))
async def test_every_strict_route_is_a_real_route(
    client: AsyncClient, method: str, template: str
) -> None:
    """Pin the declared templates to the routes that actually exist.

    The limiter matches paths against its own list rather than the router's
    tables, so a renamed endpoint would leave a template matching nothing
    and quietly drop that route to the baseline limit. A 404 here is that
    drift, caught at its source.
    """
    path = _PATH_PARAMETER.sub(str(uuid4()), template)

    response = await client.request(method, path, json={})

    assert response.status_code != 404
    assert response.headers["RateLimit-Limit"] == str(STRICT_LIMIT)


async def test_a_trailing_slash_does_not_dodge_the_strict_tier(
    client: AsyncClient,
) -> None:
    response = await client.post(f"{_STRICT_ROUTE}/", json={})

    assert response.headers["RateLimit-Limit"] == str(STRICT_LIMIT)


async def test_a_read_on_a_strict_path_stays_on_the_baseline_tier(
    client: AsyncClient,
) -> None:
    """The tier is per method: listing check-ins is not creating one."""
    response = await client.get(_STRICT_ROUTE)

    assert response.headers["RateLimit-Limit"] == str(BASELINE_LIMIT)
