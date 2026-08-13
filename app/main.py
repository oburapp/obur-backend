"""FastAPI application entrypoint: app instance, lifespan, and middleware."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import users, webhooks
from app.core.config import get_settings
from app.core.database import check_database_connection, engine
from app.core.redis import check_redis_connection, redis_client
from app.schemas.health import HealthResponse

settings = get_settings()

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

app.add_middleware(GZipMiddleware, minimum_size=_GZIP_MINIMUM_SIZE_BYTES)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router, prefix=_API_V1_PREFIX)
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
