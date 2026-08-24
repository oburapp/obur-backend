"""FastAPI application entrypoint: app instance, lifespan, and middleware."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api.v1 import (
    admin,
    checkins,
    close_friends,
    follows,
    lists,
    notifications,
    users,
    venue_categories,
    venue_saves,
    venues,
    webhooks,
)
from app.core import problems
from app.core.config import get_settings
from app.core.database import check_database_connection, engine
from app.core.problem_mapping import (
    DOMAIN_BASE_ERRORS,
    detail_for,
    extensions_for,
    problem_for,
)
from app.core.problems import ProblemError
from app.core.redis import check_redis_connection, redis_client
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    current_request_id,
)
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)
settings = get_settings()

# Headers a browser client cannot read unless CORS says so. The request id
# is how a user reports a failure we can then find; the rate-limit fields
# are what let a client pace itself instead of discovering the limit by
# hitting it.
_EXPOSED_HEADERS = [
    REQUEST_ID_HEADER,
    "RateLimit-Limit",
    "RateLimit-Remaining",
    "RateLimit-Reset",
    "Retry-After",
]

# Statuses FastAPI and Starlette raise on their own, mapped onto problem
# types so that a 404 from routing looks like every other 404.
_HTTP_STATUS_PROBLEMS = {
    status.HTTP_401_UNAUTHORIZED: problems.NOT_AUTHENTICATED,
    status.HTTP_403_FORBIDDEN: problems.NOT_RESOURCE_OWNER,
    status.HTTP_404_NOT_FOUND: problems.ROUTE_NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: problems.METHOD_NOT_ALLOWED,
}

# Responses smaller than this are not worth the CPU cost of compressing.
_GZIP_MINIMUM_SIZE_BYTES = 1000
_API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and graceful shutdown of shared resources."""
    yield
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(title="Obur API", lifespan=lifespan)

# Starlette wraps in reverse: the last one added is the outermost. Read this
# block bottom-up for the request's actual path.
#   request context -> CORS -> GZip -> rate limit -> route
# The request id has to be assigned before anything can reject a request,
# or a rate-limited caller gets a 429 with nothing to trace it by. CORS sits
# outside the limiter for the same reason in reverse: a browser cannot read
# a 429 that arrives without CORS headers.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=_GZIP_MINIMUM_SIZE_BYTES)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=_EXPOSED_HEADERS,
)
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(ProblemError)
async def handle_problem(request: Request, exc: ProblemError) -> Response:
    """Render a domain error as its declared problem type."""
    return exc.problem.response(
        detail=exc.detail,
        request_id=current_request_id(),
        headers=exc.headers,
        **exc.extensions,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> Response:
    """Normalise FastAPI's own validation shape into a problem response.

    Its default body is a bare list under `detail`, which is a second shape
    for a client to parse. The field errors survive as an extension member
    rather than being flattened away.
    """
    return problems.VALIDATION_FAILED.response(
        detail=problems.VALIDATION_FAILED.detail,
        request_id=current_request_id(),
        errors=[
            {
                "field": ".".join(str(part) for part in error["loc"][1:]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ],
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> Response:
    """Map framework-raised HTTP errors onto problem types.

    Registered against Starlette's exception rather than FastAPI's subclass
    on purpose: routing 404s and method mismatches are raised by the router
    itself, so a handler bound to the subclass never sees them and those two
    paths become the one place the contract breaks.
    """
    problem = _HTTP_STATUS_PROBLEMS.get(exc.status_code)
    if problem is None:
        problem = problems.INTERNAL_ERROR
    return problem.response(
        detail=problem.title,
        request_id=current_request_id(),
        headers=getattr(exc, "headers", None),
    )


async def handle_domain_error(request: Request, exc: Exception) -> Response:
    """Translate a domain exception into its declared problem type.

    Registered per domain base class rather than on `Exception`, because
    Starlette routes a bare `Exception` handler through `ServerErrorMiddleware`,
    which re-raises after responding so the server can log a crash. These are
    expected outcomes, not crashes, and must not be re-raised.

    An unmapped subclass falls through to a generic problem rather than
    exposing its message — a new error type is then visibly wrong in the
    logs instead of silently leaking.
    """
    problem = problem_for(exc)
    if problem is None:
        logger.error("unmapped domain error: %s", type(exc).__name__, exc_info=exc)
        return problems.INTERNAL_ERROR.response(
            detail=problems.INTERNAL_ERROR.detail,
            request_id=current_request_id(),
        )

    return problem.response(
        detail=detail_for(exc, problem),
        request_id=current_request_id(),
        **extensions_for(exc),
    )


for _domain_error in DOMAIN_BASE_ERRORS:
    app.add_exception_handler(_domain_error, handle_domain_error)


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
    """Last resort: a generic problem, never the exception.

    RFC 9457 is explicit that error responses must not carry implementation
    detail; the exception goes to the log, where `request_id` ties it back
    to what the caller saw.
    """
    logger.exception("unhandled error")
    return problems.INTERNAL_ERROR.response(
        detail=problems.INTERNAL_ERROR.detail,
        request_id=current_request_id(),
    )


app.include_router(users.router, prefix=_API_V1_PREFIX)
app.include_router(venues.router, prefix=_API_V1_PREFIX)
app.include_router(venue_categories.router, prefix=_API_V1_PREFIX)
app.include_router(checkins.router, prefix=_API_V1_PREFIX)
app.include_router(follows.router, prefix=_API_V1_PREFIX)
app.include_router(close_friends.router, prefix=_API_V1_PREFIX)
app.include_router(lists.router, prefix=_API_V1_PREFIX)
app.include_router(venue_saves.router, prefix=_API_V1_PREFIX)
app.include_router(notifications.router, prefix=_API_V1_PREFIX)
app.include_router(admin.router, prefix=_API_V1_PREFIX)
app.include_router(webhooks.router, prefix=_API_V1_PREFIX)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Report application health, based on real dependency connectivity."""
    database_ok = await check_database_connection()
    redis_ok = await check_redis_connection()
    healthy = database_ok and redis_ok

    body = HealthResponse(
        status="ok" if healthy else "unhealthy",
        database=database_ok,
        redis=redis_ok,
    )

    return JSONResponse(
        status_code=(
            status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=body.model_dump(),
    )
