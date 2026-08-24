"""Matching a request to a route template before the router has run.

Middleware runs ahead of Starlette's router, so `scope["route"]` is empty
while a request is still being screened. Anything that must decide per route
*in order to refuse* — which rate-limit tier applies — cannot read it, and
reading it anyway fails quietly: a strict route served at the baseline limit
looks exactly like a working limiter.

The router's own tables are not usable here. FastAPI keeps included routers
as opaque objects whose prefixes live in private attributes, so reassembling
the full templates would bind this to one framework version and break
silently on an upgrade.

Instead the templates this module cares about are declared explicitly, in
`STRICT_ROUTES`, and compiled once. The cost of an explicit list is that it
can drift from the real routes; `tests/unit/test_rate_limit_middleware.py`
pins each entry to a live route so drift fails loudly instead.
"""

import re
from re import Pattern

# `{name}` in a route template stands for one path segment.
_PARAMETER = re.compile(r"\{[^/}]+\}")
_ONE_SEGMENT = r"[^/]+"


def compile_template(template: str) -> Pattern[str]:
    """Turn `/api/v1/users/{user_id}/follow` into a regex matching one path.

    The literal parts are escaped and the parameters are not, so splitting on
    the parameters first is what keeps the two from interfering.

    A trailing slash is accepted: the router redirects it, and a tier that a
    trailing slash could dodge would not be a tier.
    """
    literals = _PARAMETER.split(template)
    pattern = _ONE_SEGMENT.join(re.escape(literal) for literal in literals)
    return re.compile(f"^{pattern}/?$")


def matches_any(path: str, patterns: tuple[Pattern[str], ...]) -> bool:
    """Whether `path` matches one of the compiled templates."""
    return any(pattern.match(path) for pattern in patterns)
