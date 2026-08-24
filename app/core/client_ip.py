"""Resolving the caller's address from behind reverse proxies.

Behind a proxy `request.client.host` is the proxy, so the caller's address
has to come from `X-Forwarded-For`. **Reading that header the obvious way is
a vulnerability, not a detail.** The header is client-controlled: everything
to the left of what our own proxy appended was written by whoever sent the
request. Taking the leftmost entry — the one that looks like the original
client — lets an attacker spoof a different value per request, land each in
its own rate-limit counter, and never fill any of them.

This has been filed as a security advisory against shipped frameworks. See
ADR-0014 in obur-docs for the sources.

The rule here is "rightmost-ish": count in from the right by the number of
proxies we actually control, and take the first entry we did not receive
from one of them. `TRUSTED_PROXY_COUNT` is that number, and it has no
default because a wrong value fails silently in both directions — too high
reads a forged value, too low lumps everyone behind the proxy into one
counter.
"""

import ipaddress
import logging

from fastapi import Request

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_FORWARDED_FOR_HEADER = "x-forwarded-for"


def _valid_address(candidate: str) -> str | None:
    """Return `candidate` if it parses as an IP address, else None.

    Validation is not cosmetic: the result becomes part of a cache key, and
    an attacker chooses the header's contents. An unvalidated value lets
    them pick arbitrarily long or arbitrarily many distinct keys.
    """
    try:
        return str(ipaddress.ip_address(candidate.strip()))
    except ValueError:
        return None


def resolve_client_ip(request: Request) -> str | None:
    """Return the caller's address, or None when it can't be established.

    None is a real answer, not an error: a caller with no resolvable address
    still has to be rate limited, and the middleware treats it as its own
    bucket rather than exempting it.
    """
    direct = request.client.host if request.client else None
    proxy_count = get_settings().trusted_proxy_count

    if proxy_count == 0:
        # Nothing in front of us, so the header — if present at all — was
        # written by the caller and is worthless. The socket address is the
        # only trustworthy source.
        return _valid_address(direct) if direct else None

    # Only the last instance of the header matters; earlier ones may have
    # been supplied by the client alongside the one a proxy appended.
    forwarded = request.headers.getlist(_FORWARDED_FOR_HEADER)
    if not forwarded:
        return _valid_address(direct) if direct else None

    entries = [entry.strip() for entry in forwarded[-1].split(",")]

    # `direct` is the nearest proxy and is not in the header, so it accounts
    # for one of the hops we trust. Skipping the rest from the right leaves
    # the first entry that a proxy we control did not write.
    skip = proxy_count - 1
    index = len(entries) - 1 - skip

    if index < 0:
        # Fewer entries than configured hops: the deployment does not match
        # the setting. Refusing to guess is the point — guessing here is how
        # a limiter silently starts trusting forged input.
        logger.warning(
            "X-Forwarded-For has %d entries but %d proxies are configured; "
            "cannot establish a trustworthy client address",
            len(entries),
            proxy_count,
        )
        return None

    return _valid_address(entries[index])
