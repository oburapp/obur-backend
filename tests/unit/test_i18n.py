"""Tests for locale constants and request-time locale resolution."""

from unittest.mock import MagicMock

from fastapi import Request

from app.core.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, parse_accept_language
from app.core.locale import resolve_locale
from app.models.user import User


def _request(accept_language: str | None) -> Request:
    request = MagicMock(spec=Request)
    request.headers = (
        {} if accept_language is None else {"accept-language": accept_language}
    )
    return request


def test_default_locale_is_supported() -> None:
    """A fallback nothing can serve would be worse than no fallback."""
    assert DEFAULT_LOCALE in SUPPORTED_LOCALES


def test_parse_accept_language_returns_nothing_for_an_absent_header() -> None:
    assert parse_accept_language(None) == []
    assert parse_accept_language("") == []


def test_parse_accept_language_drops_unsupported_languages() -> None:
    assert parse_accept_language("de,fr") == []


def test_parse_accept_language_reduces_a_regional_tag_to_its_language() -> None:
    """`en-GB` and `en-US` share one translation table — a venue category
    name doesn't differ between them.
    """
    assert parse_accept_language("en-GB") == ["en"]


def test_parse_accept_language_orders_by_quality() -> None:
    assert parse_accept_language("tr;q=0.5,en;q=0.9") == ["en", "tr"]


def test_parse_accept_language_keeps_header_order_for_equal_quality() -> None:
    """The spec treats equal q-values as ordered by appearance."""
    assert parse_accept_language("en,tr") == ["en", "tr"]
    assert parse_accept_language("tr,en") == ["tr", "en"]


def test_parse_accept_language_skips_malformed_entries() -> None:
    """A broken header is not a reason to refuse to serve the page."""
    assert parse_accept_language("!!!,en") == ["en"]
    assert parse_accept_language("en;q=abc,tr") == ["tr"]


def test_parse_accept_language_skips_a_numeric_looking_but_invalid_quality() -> None:
    """`1.2.3` is digits and dots, so it satisfies the entry pattern and
    only fails when parsed as a number. Without the guard this raises
    mid-request on a header nobody controls.
    """
    assert parse_accept_language("en;q=1.2.3,tr") == ["tr"]
    assert parse_accept_language("en;q=.,tr") == ["tr"]


async def test_resolve_locale_prefers_the_signed_in_users_own_setting() -> None:
    """An explicit choice in settings should follow the user onto a
    borrowed device whose browser says something else.
    """
    viewer = User(locale="en")

    assert await resolve_locale(_request("tr"), viewer) == "en"


async def test_resolve_locale_falls_back_to_the_header_for_anonymous_callers() -> None:
    assert await resolve_locale(_request("en"), None) == "en"


async def test_resolve_locale_ignores_an_unsupported_user_locale() -> None:
    """A stale `locale` value must not make the catalog unreadable."""
    viewer = User(locale="de")

    assert await resolve_locale(_request("en"), viewer) == "en"


async def test_resolve_locale_falls_back_to_the_default_when_nothing_matches() -> None:
    assert await resolve_locale(_request("de"), None) == DEFAULT_LOCALE
    assert await resolve_locale(_request(None), None) == DEFAULT_LOCALE
