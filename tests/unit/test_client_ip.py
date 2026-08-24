"""Unit tests for X-Forwarded-For resolution.

These cover a security control, not a convenience: reading the header from
the wrong end lets a caller spoof a fresh identity per request and never
fill a rate-limit counter. ADR-0014 records the advisories where exactly
that shipped. The assertions below are therefore about *which* entry is
chosen, not merely that some address comes back.
"""

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from starlette.datastructures import Headers

from app.core.client_ip import resolve_client_ip

_TRUE_CLIENT = "203.0.113.7"
_OUR_PROXY = "198.51.100.1"
_SOCKET_PEER = "10.0.0.9"
_SPOOFED = "1.2.3.4"


def _request(
    *, forwarded: list[str] | None = None, peer: str | None = _SOCKET_PEER
) -> MagicMock:
    """A request stub carrying only what resolution actually reads."""
    raw = [(b"x-forwarded-for", value.encode()) for value in forwarded or []]
    request = MagicMock()
    request.headers = Headers(raw=raw)
    request.client = MagicMock(host=peer) if peer is not None else None
    return request


@pytest.fixture(autouse=True)
def _proxy_count(mocker: MockerFixture) -> Callable[[int], None]:
    """Set the trusted proxy count per test; it has no default in Settings."""

    def _set(count: int) -> None:
        mocker.patch(
            "app.core.client_ip.get_settings",
            return_value=MagicMock(trusted_proxy_count=count),
        )

    return _set


def test_uses_the_socket_address_when_no_proxy_is_configured(
    _proxy_count: Callable[[int], None],
) -> None:
    _proxy_count(0)

    assert resolve_client_ip(_request(forwarded=[_SPOOFED])) == _SOCKET_PEER


def test_ignores_a_forged_header_when_no_proxy_is_configured(
    _proxy_count: Callable[[int], None],
) -> None:
    """With nothing in front of us the header is caller-written and worthless."""
    _proxy_count(0)

    assert resolve_client_ip(_request(forwarded=[_SPOOFED])) != _SPOOFED


def test_reads_the_rightmost_entry_behind_one_proxy(
    _proxy_count: Callable[[int], None],
) -> None:
    _proxy_count(1)

    resolved = resolve_client_ip(_request(forwarded=[f"{_SPOOFED}, {_TRUE_CLIENT}"]))

    assert resolved == _TRUE_CLIENT


def test_a_spoofed_prefix_does_not_change_the_resolved_address(
    _proxy_count: Callable[[int], None],
) -> None:
    """The whole point: prepended entries must not produce a new identity.

    An attacker controls everything left of what our proxy appended. If any
    of it reached the result, each request would land in its own counter and
    the limit would never be reached.
    """
    _proxy_count(1)

    without = resolve_client_ip(_request(forwarded=[_TRUE_CLIENT]))
    with_spoof = resolve_client_ip(
        _request(forwarded=[f"{_SPOOFED}, 5.6.7.8, {_TRUE_CLIENT}"])
    )

    assert without == with_spoof == _TRUE_CLIENT


def test_skips_our_own_proxies_when_two_are_configured(
    _proxy_count: Callable[[int], None],
) -> None:
    _proxy_count(2)

    resolved = resolve_client_ip(
        _request(forwarded=[f"{_SPOOFED}, {_TRUE_CLIENT}, {_OUR_PROXY}"])
    )

    assert resolved == _TRUE_CLIENT


def test_uses_only_the_last_header_instance(
    _proxy_count: Callable[[int], None],
) -> None:
    """A client may send its own header alongside the one a proxy appended."""
    _proxy_count(1)

    resolved = resolve_client_ip(_request(forwarded=[_SPOOFED, _TRUE_CLIENT]))

    assert resolved == _TRUE_CLIENT


def test_returns_none_when_there_are_fewer_entries_than_proxies(
    _proxy_count: Callable[[int], None],
) -> None:
    """A topology mismatch must refuse to guess rather than trust forged input."""
    _proxy_count(3)

    assert resolve_client_ip(_request(forwarded=[_TRUE_CLIENT])) is None


def test_returns_none_for_a_malformed_address(
    _proxy_count: Callable[[int], None],
) -> None:
    """The result becomes part of a cache key, and the caller chooses it."""
    _proxy_count(1)

    assert resolve_client_ip(_request(forwarded=["not-an-address"])) is None


def test_rejects_an_oversized_value_that_would_bloat_a_cache_key(
    _proxy_count: Callable[[int], None],
) -> None:
    _proxy_count(1)

    assert resolve_client_ip(_request(forwarded=["9" * 5000])) is None


def test_falls_back_to_the_socket_address_when_the_header_is_absent(
    _proxy_count: Callable[[int], None],
) -> None:
    _proxy_count(1)

    assert resolve_client_ip(_request()) == _SOCKET_PEER


def test_returns_none_when_there_is_no_client_at_all(
    _proxy_count: Callable[[int], None],
) -> None:
    """ASGI does not guarantee a client; a limiter must still cope."""
    _proxy_count(0)

    assert resolve_client_ip(_request(peer=None)) is None


def test_accepts_an_ipv6_address(_proxy_count: Callable[[int], None]) -> None:
    _proxy_count(1)

    assert resolve_client_ip(_request(forwarded=["2001:db8::1"])) == "2001:db8::1"
