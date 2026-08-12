"""Async Redis client and connectivity check."""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

settings = get_settings()

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def check_redis_connection() -> bool:
    """Verify Redis is reachable via `PING`."""
    try:
        return bool(await redis_client.ping())
    except RedisError:
        return False
