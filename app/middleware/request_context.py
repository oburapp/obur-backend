"""Request correlation, structured logging, and latency measurement.

Every request gets an id, echoed back so a person reporting a failure can
name it and have it found. The same id goes on every log line and into every
problem response (ADR-0015).

An inbound `X-Request-ID` is honoured only if it validates. That is not
politeness: the value is written to every log line for the request, and an
unvalidated client-supplied string is a log-injection vector — OWASP calls
out carriage returns, line feeds, and delimiters specifically.

`traceparent` is deliberately not handled here. There is one service and no
second hop to correlate with; ADR-0015 records the conditions that would
change that.
"""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("obur.request")

REQUEST_ID_HEADER = "X-Request-ID"

# Hex, hyphens, and underscores only, bounded length. Rejects anything that
# could break a log line or bloat it.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# The current request's id, readable from anywhere in the request without
# threading it through every signature — the exception handlers in
# app/main.py need it and are far from this module.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_MILLISECONDS = 1000

# Path segments that look like an identifier rather than a route literal:
# UUIDs, and long digit or hex runs. Substituted when no route template is
# available, so a fallback path still aggregates and still carries nothing
# about who was asked for.
_REDACTED_SEGMENT = re.compile(
    r"(?<=/)(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9]+|[0-9a-fA-F]{16,})(?=/|$)"
)
_IDENTIFIER_PLACEHOLDER = "{id}"


def current_request_id() -> str | None:
    """Return this request's id, or None outside a request."""
    return request_id_var.get()


def _resolve_request_id(request: Request) -> str:
    """Honour a well-formed inbound id, otherwise generate one."""
    supplied = request.headers.get(REQUEST_ID_HEADER)
    if supplied is not None and _VALID_REQUEST_ID.match(supplied):
        return supplied
    return uuid.uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, then log the request's outcome and duration.

    Registered outermost so that a request rejected further in — by the rate
    limiter, say — still receives an id and still gets measured. A limiter
    that runs before the id is assigned produces rejections with nothing to
    trace them by.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _resolve_request_id(request)
        token = request_id_var.set(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # Logged here so the duration and id are recorded even for a
            # request that never produced a response; app/main.py's handler
            # is what turns it into one.
            logger.exception(
                "request failed",
                extra=self._fields(request, request_id, started, status=500),
            )
            raise
        finally:
            request_id_var.reset(token)

        logger.info(
            "request completed",
            extra=self._fields(
                request, request_id, started, status=response.status_code
            ),
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _fields(
        request: Request, request_id: str, started: float, *, status: int
    ) -> dict[str, object]:
        """Structured fields for one request.

        Deliberately excludes the client address and anything derived from
        it. OWASP's exclusion list does not name source IP, so this is
        stricter than the baseline — ADR-0014's position is that an address
        may be counted against but not recorded, and a log line is a record.
        """
        return {
            "request_id": request_id,
            "method": request.method,
            # The route pattern, not the path: `/venues/{venue_id}` rather
            # than a specific id, so lines aggregate and no identifier leaks
            # into the log through the URL.
            "route": _route_pattern(request),
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * _MILLISECONDS, 2),
        }


def _route_pattern(request: Request) -> str:
    """The matched route's template, falling back to the raw path.

    A request refused before routing — by the limiter — has no template yet,
    and neither does one that matched nothing. Identifier-shaped segments are
    replaced in that fallback: the whole reason for logging the template is
    that lines aggregate and no identifier reaches the log through the URL,
    and a fallback that leaks them would defeat it on exactly the paths that
    are most interesting to read.
    """
    path_format = getattr(request.scope.get("route"), "path_format", None)
    if isinstance(path_format, str):
        return _with_router_prefix(request.url.path, path_format)
    return _REDACTED_SEGMENT.sub(_IDENTIFIER_PLACEHOLDER, request.url.path)


def _with_router_prefix(path: str, template: str) -> str:
    """Restore the prefix an included router strips from its own templates.

    FastAPI reports `/venues/{venue_id}` for a route included under
    `/api/v1`, so the template alone would merge two routes that differ only
    by prefix. The prefix is whatever the real path holds ahead of the
    template's segments, recovered by counting them — the router's tables
    are private and reassembling them would bind this to one version.
    """
    depth = template.count("/")
    if depth == 0:
        return path
    return f"{path.rstrip('/').rsplit('/', depth)[0]}{template}"
