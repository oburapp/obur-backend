"""Venue score (PDD §8, ADR-0020 in obur-docs): the headline tier, the
four criteria tiers, and the number of check-ins behind them.

The sample comes from `rls_venue_score_sample`, a narrow SECURITY DEFINER
function, so the anonymous platform statistic never varies with the
caller's own RLS view (for instance hiding public check-ins of someone
they blocked) and then gets cached for everyone.

Results are cached in Redis under `venue:{id}:score:v{score_version}`.
Database triggers move `score_version` on every write that can change the
score, so this module never invalidates anything; a superseded key just
stops being read and expires. If Redis is unavailable the score is
computed directly and the request still succeeds.
"""

import logging
import uuid

from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import Float, Integer, RowMapping, column, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_client
from app.core.scoring import Tier, tier_from_sample
from app.models.venue import Venue
from app.schemas.venue_score import CriteriaTiers, VenueScore

logger = logging.getLogger(__name__)

SCORE_CACHE_TTL_SECONDS = 600
_CRITERIA = ("taste", "service", "ambiance", "value")


def score_cache_key(venue_id: uuid.UUID, version: int) -> str:
    """The Redis key for a venue's score at a given `score_version`."""
    return f"venue:{venue_id}:score:v{version}"


_SAMPLE_COLUMNS = ["checkin_count", "overall_mean", "overall_sd"] + [
    f"{criterion}_{stat}" for criterion in _CRITERIA for stat in ("mean", "sd")
]


async def _sample(session: AsyncSession, venue_id: uuid.UUID) -> RowMapping:
    sample = func.rls_venue_score_sample(venue_id).table_valued(
        column(_SAMPLE_COLUMNS[0], Integer),
        *(column(name, Float) for name in _SAMPLE_COLUMNS[1:]),
    )
    return (await session.execute(select(sample))).one()._mapping


async def compute_venue_score(session: AsyncSession, venue_id: uuid.UUID) -> VenueScore:
    """Compute a venue's score from the database, bypassing the cache."""
    row = await _sample(session, venue_id)
    count = row["checkin_count"]

    def tier(prefix: str) -> Tier | None:
        return tier_from_sample(count, row[f"{prefix}_mean"], row[f"{prefix}_sd"])

    return VenueScore(
        tier=tier("overall"),
        criteria=CriteriaTiers(
            taste=tier("taste"),
            service=tier("service"),
            ambiance=tier("ambiance"),
            value=tier("value"),
        ),
        checkin_count=count,
    )


async def _cached(key: str) -> VenueScore | None:
    try:
        raw = await redis_client.get(key)
    except RedisError as e:
        logger.warning("Venue score cache read failed, computing directly: %s", e)
        return None
    if raw is None:
        return None
    try:
        return VenueScore.model_validate_json(raw)
    except ValidationError:
        logger.warning("Discarding unreadable venue score cache entry %s", key)
        return None


async def _store(key: str, score: VenueScore) -> None:
    try:
        await redis_client.set(key, score.model_dump_json(), ex=SCORE_CACHE_TTL_SECONDS)
    except RedisError as e:
        logger.warning("Venue score cache write failed: %s", e)


async def get_venue_score(session: AsyncSession, venue: Venue) -> VenueScore:
    """A venue's score, from the cache when the current version is there."""
    key = score_cache_key(venue.id, venue.score_version)
    cached = await _cached(key)
    if cached is not None:
        return cached
    score = await compute_venue_score(session, venue.id)
    await _store(key, score)
    return score
