"""Redis-backed rate limiting. See ADR-0014 in obur-docs.

Fixed-window counters, keyed on `user_id` for an authenticated caller and on
an HMAC of the resolved address for an anonymous one. The window algorithm
is chosen for memory safety rather than simplicity: a sliding-window log
stores one entry per request per key, and with address-derived keys an
attacker controls how many keys exist, which turns a more precise limiter
into a memory-exhaustion vector against the store protecting us. A fixed
window is O(1) per key and expires itself.

The increment and the expiry are one atomic script. Split apart, a failure
between them leaves a counter with no TTL — permanent, and the caller it
belongs to locked out for good.

On store failure the tiers diverge: strict fails closed, baseline fails
open. The threats differ, so the safe direction differs.
"""

import hashlib
import hmac
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from re import Pattern

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core import problems
from app.core.client_ip import resolve_client_ip
from app.core.config import get_settings
from app.core.redis import redis_client
from app.middleware.request_context import current_request_id
from app.middleware.route_match import compile_template, matches_any

logger = logging.getLogger(__name__)

# Every counter lives under one prefix so the whole namespace can be
# addressed at once — the test fixture that resets counters between tests
# scans for exactly this, and nothing else in Redis shares it.
KEY_NAMESPACE = "rl"

WINDOW_SECONDS = 3600

# Starting values, calibratable from one place — ADR-0014 records how they
# were chosen. Real anonymous browsing is a few hundred requests an hour,
# because one page view is several API calls.
BASELINE_LIMIT = 600
STRICT_LIMIT = 30

# Routes whose repeated abuse damages data rather than merely costing
# bandwidth: rating manipulation, spam venues, follow-spam, and now
# report submission (Phase 10): unlimited reporting is itself an abuse
# vector (PDD §17). Matched on the route template, so path parameters
# don't fragment the rule.
STRICT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/checkins"),
        ("POST", "/api/v1/venues"),
        ("POST", "/api/v1/users/{user_id}/follow"),
        ("POST", "/api/v1/checkins/{checkin_id}/report"),
        ("POST", "/api/v1/users/{user_id}/report"),
        ("POST", "/api/v1/venues/{venue_id}/report"),
    }
)

# Compiled once, since the tier has to be decided on every request before
# the router has resolved anything. Keyed by method so a GET on a strict
# path is not needlessly restricted.
_STRICT_PATTERNS: dict[str, tuple[Pattern[str], ...]] = {
    method: tuple(
        compile_template(template) for verb, template in STRICT_ROUTES if verb == method
    )
    for method, _ in STRICT_ROUTES
}

_ANONYMOUS_KEY_LENGTH = 32
_UNRESOLVED_ADDRESS_KEY = "unresolved"

# One round trip, and atomic: a counter that is incremented without ever
# receiving a TTL never expires, and locks its caller out permanently.
_INCREMENT_AND_EXPIRE = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {current, redis.call('TTL', KEYS[1])}
"""


@dataclass(frozen=True)
class Tier:
    """A named limit and the direction it fails when the store is down."""

    name: str
    limit: int
    fail_closed: bool


BASELINE = Tier(name="baseline", limit=BASELINE_LIMIT, fail_closed=False)
STRICT = Tier(name="strict", limit=STRICT_LIMIT, fail_closed=True)


def _anonymous_key(client_ip: str | None) -> str:
    """Derive a counting key from an address without recording it.

    HMAC rather than a bare hash: the address space is small enough to
    enumerate exhaustively, so an unkeyed digest would be trivially
    reversible. The result is held only for the window and never logged.

    A caller whose address can't be resolved still gets counted, in a shared
    bucket. Exempting them would make "send an unparseable header" the way
    around the limiter.
    """
    material = client_ip or _UNRESOLVED_ADDRESS_KEY
    digest = hmac.new(
        get_settings().rate_limit_secret.encode("utf-8"),
        material.encode("utf-8"),
        hashlib.sha256,
    )
    return digest.hexdigest()[:_ANONYMOUS_KEY_LENGTH]


def _scope(request: Request) -> str:
    """Identify the caller: their user id if known, else a derived key.

    `request.state.user_id` is set by the auth dependency when one resolved.
    The middleware runs before dependencies, so an authenticated caller is
    keyed anonymously on their first request and by id afterwards — accepted,
    since both keys are bounded and the limit is per-caller either way.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        return f"u:{user_id}"
    return f"a:{_anonymous_key(resolve_client_ip(request))}"


def _tier_for(request: Request) -> Tier:
    """Pick the tier from the path, without waiting for the router.

    `scope["route"]` is empty at this point — the router runs after the
    middleware stack — so matching the path against the declared templates
    is the only way to know the tier while there is still time to refuse.
    """
    patterns = _STRICT_PATTERNS.get(request.method)
    if patterns and matches_any(request.url.path, patterns):
        return STRICT
    return BASELINE


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Count each caller's requests and refuse the ones over the limit."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        tier = _tier_for(request)
        window = int(time.time()) // WINDOW_SECONDS
        key = f"{KEY_NAMESPACE}:{tier.name}:{_scope(request)}:{window}"

        try:
            count, ttl = await redis_client.eval(
                _INCREMENT_AND_EXPIRE, 1, key, WINDOW_SECONDS
            )
        except RedisError:
            return await self._on_store_failure(request, call_next, tier)

        if count > tier.limit:
            return self._refuse(tier, retry_after=max(ttl, 1))

        response = await call_next(request)
        self._annotate(response, tier=tier, count=count, ttl=ttl)
        return response

    async def _on_store_failure(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        tier: Tier,
    ) -> Response:
        """Fail in the direction that is safe for this tier.

        Strict routes damage data when abused, so they stop. Reads keep
        serving: making the counter store a hard dependency of every request
        would trade a slow privacy risk for an outage, on infrastructure
        with no availability guarantee.
        """
        logger.error(
            "rate limit store unavailable; tier=%s failing %s",
            tier.name,
            "closed" if tier.fail_closed else "open",
        )
        if tier.fail_closed:
            return problems.RATE_LIMITER_UNAVAILABLE.response(
                detail="Request limits cannot be verified. Try again shortly.",
                request_id=current_request_id(),
            )
        return await call_next(request)

    @staticmethod
    def _refuse(tier: Tier, *, retry_after: int) -> Response:
        return problems.RATE_LIMITED.response(
            detail=f"Rate limit of {tier.limit} requests per hour exceeded.",
            request_id=current_request_id(),
            headers={
                "Retry-After": str(retry_after),
                "RateLimit-Limit": str(tier.limit),
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": str(retry_after),
            },
        )

    @staticmethod
    def _annotate(response: Response, *, tier: Tier, count: int, ttl: int) -> None:
        """Advertise the remaining quota so a client can pace itself."""
        response.headers["RateLimit-Limit"] = str(tier.limit)
        response.headers["RateLimit-Remaining"] = str(max(tier.limit - count, 0))
        response.headers["RateLimit-Reset"] = str(max(ttl, 0))
