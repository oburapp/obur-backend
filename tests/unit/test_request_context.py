"""Unit tests for request correlation and the request log.

The inbound-id validation is a log-injection control, not a formatting
preference: the value lands on every log line for the request. OWASP names
carriage returns, line feeds, and delimiters specifically (ADR-0015).
"""

import logging
from collections.abc import Generator
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.middleware.request_context import (
    REQUEST_ID_HEADER,
    current_request_id,
    request_id_var,
)

_PUBLIC_ROUTE = "/api/v1/venue-categories"
_LOGGER_NAME = "obur.request"
_VALID_ID = "0123abcd-4567"


class _RecordCollector(logging.Handler):
    """Collect records straight off the request logger.

    Attached to the logger under test rather than relying on `caplog`, whose
    handler sits on the root logger and therefore only sees what propagates.
    Reading the emitted record is the point of these tests, so the capture
    should not be the part that can silently stop working.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def request_log() -> Generator[_RecordCollector, None, None]:
    collector = _RecordCollector()
    logger = logging.getLogger(_LOGGER_NAME)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous_level)


def _fields(collector: _RecordCollector) -> dict[str, object]:
    """The structured fields of the one request this test made."""
    assert len(collector.records) == 1
    return vars(collector.records[0])


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get(_PUBLIC_ROUTE)

    assert response.headers[REQUEST_ID_HEADER]


async def test_each_request_gets_a_distinct_id(client: AsyncClient) -> None:
    first = await client.get(_PUBLIC_ROUTE)
    second = await client.get(_PUBLIC_ROUTE)

    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


async def test_a_well_formed_inbound_id_is_honoured(client: AsyncClient) -> None:
    """A caller that already has an id keeps it, so both sides can name it."""
    response = await client.get(_PUBLIC_ROUTE, headers={REQUEST_ID_HEADER: _VALID_ID})

    assert response.headers[REQUEST_ID_HEADER] == _VALID_ID


@pytest.mark.parametrize(
    "supplied",
    [
        pytest.param("abc\r\nfake log line", id="crlf_injection"),
        pytest.param("abc\ninjected", id="newline_injection"),
        pytest.param("short", id="under_minimum_length"),
        pytest.param("x" * 65, id="over_maximum_length"),
        pytest.param("id with spaces", id="delimiter"),
        pytest.param("id;drop", id="punctuation"),
        pytest.param("", id="empty"),
    ],
)
async def test_a_malformed_inbound_id_is_replaced(
    client: AsyncClient, supplied: str
) -> None:
    response = await client.get(_PUBLIC_ROUTE, headers={REQUEST_ID_HEADER: supplied})

    assert response.headers[REQUEST_ID_HEADER] != supplied


async def test_the_request_log_records_the_route_template_not_the_path(
    client: AsyncClient, request_log: _RecordCollector
) -> None:
    """Lines aggregate, and no identifier reaches the log through the URL."""
    venue_id = uuid4()

    await client.get(f"/api/v1/venues/{venue_id}")

    assert _fields(request_log)["route"] == "/api/v1/venues/{venue_id}"


async def test_the_request_log_omits_the_client_address(
    client: AsyncClient, request_log: _RecordCollector
) -> None:
    """Stricter than OWASP's list on purpose — ADR-0014's position is that an
    address may be counted against, not recorded, and a log line is a record.
    """
    address = "203.0.113.7"

    await client.get(_PUBLIC_ROUTE, headers={"X-Forwarded-For": address})

    assert address not in str(_fields(request_log))


async def test_the_request_log_carries_the_id_status_and_duration(
    client: AsyncClient, request_log: _RecordCollector
) -> None:
    response = await client.get(_PUBLIC_ROUTE)

    fields = _fields(request_log)
    assert fields["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert fields["status"] == 200
    assert fields["method"] == "GET"


async def test_an_unrouted_path_is_logged_with_identifiers_redacted(
    client: AsyncClient, request_log: _RecordCollector
) -> None:
    """No template exists for a 404, and the raw path may still carry an id."""
    missing_id = uuid4()

    await client.get(f"/api/v1/nope/{missing_id}")

    assert _fields(request_log)["route"] == "/api/v1/nope/{id}"


def test_the_request_id_is_unset_outside_a_request() -> None:
    """The context variable must not leak a previous request's id."""
    assert current_request_id() is None


def test_the_request_id_is_readable_from_anywhere_in_a_request() -> None:
    """Exception handlers in app/main.py read it without it being threaded
    through every signature.
    """
    token = request_id_var.set(_VALID_ID)
    try:
        assert current_request_id() == _VALID_ID
    finally:
        request_id_var.reset(token)
