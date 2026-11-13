"""Integration tests for the venue score and its cache version (ADR-0020
in obur-docs) against the real database and Redis.

Every event that can move a score is asserted to move
`venues.score_version`, read straight from the database, because that
version is the cache's only invalidation. Account deletion is included:
it reaches check-ins through a foreign-key cascade no application code
sees.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.redis import redis_client
from app.core.scoring import SCORE_FLOOR
from app.core.visibility import Visibility
from app.models.checkin import Checkin
from app.models.user import User, UserStatus
from app.models.venue import Venue
from app.services import block as block_service
from app.services import checkin as checkin_service
from app.services.venue_score import (
    compute_venue_score,
    get_venue_score,
    score_cache_key,
)
from tests.integration.tagging_factories import create_user, create_venue, post_checkin


async def _version(session: AsyncSession, venue: Venue) -> int:
    return (
        await session.execute(select(Venue.score_version).where(Venue.id == venue.id))
    ).scalar_one()


async def _fill(session: AsyncSession, venue: Venue, count: int = SCORE_FLOOR) -> None:
    """`count` public check-ins from distinct users, each rated 4/3/3/2."""
    for _ in range(count):
        author = await create_user(session)
        await post_checkin(session, author, venue)


async def _set_status(session: AsyncSession, user: User, status: str) -> None:
    await set_current_user_identity(session, user.id)
    user.status = status
    await session.flush()


async def test_below_the_floor_there_are_no_tiers(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    await _fill(db_session, venue, SCORE_FLOOR - 1)

    score = await compute_venue_score(db_session, venue.id)

    assert score.tier is None
    assert score.criteria.taste is None
    assert score.checkin_count == SCORE_FLOOR - 1


async def test_at_the_floor_each_criterion_gets_its_own_tier(
    db_session: AsyncSession,
) -> None:
    """Identical ratings have no spread, so each bound equals its mean:
    a visit averages 3.0, taste 4, service and ambiance 3, value 2.
    """
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    await _fill(db_session, venue)

    score = await compute_venue_score(db_session, venue.id)

    assert score.tier == "somewhat_favorable"
    assert score.criteria.taste == "extremely_favorable"
    assert score.criteria.service == "somewhat_favorable"
    assert score.criteria.ambiance == "somewhat_favorable"
    assert score.criteria.value == "somewhat_unfavorable"
    assert score.checkin_count == SCORE_FLOOR


async def test_only_public_live_checkins_of_unsuspended_accounts_count(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    await _fill(db_session, venue, 2)
    private_author = await create_user(db_session)
    await post_checkin(db_session, private_author, venue, visibility=Visibility.PRIVATE)
    deleter = await create_user(db_session)
    deleted = await post_checkin(db_session, deleter, venue)
    await checkin_service.soft_delete_checkin(
        db_session, deleted.id, current_user=deleter
    )
    frozen = await create_user(db_session)
    await post_checkin(db_session, frozen, venue)
    await _set_status(db_session, frozen, UserStatus.FROZEN)
    suspended = await create_user(db_session)
    await post_checkin(db_session, suspended, venue)
    await _set_status(db_session, suspended, UserStatus.SUSPENDED)

    score = await compute_venue_score(db_session, venue.id)

    assert score.checkin_count == 3


async def test_the_score_does_not_depend_on_who_asks(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    author = await create_user(db_session)
    await post_checkin(db_session, author, venue)
    blocker = await create_user(db_session)
    await block_service.create_block(
        db_session, blocker_id=blocker.id, blocked_id=author.id
    )

    as_blocker = await compute_venue_score(db_session, venue.id)
    await set_current_user_identity(db_session, owner.id)
    as_owner = await compute_venue_score(db_session, venue.id)

    assert as_blocker.checkin_count == as_owner.checkin_count == 1


async def test_writes_that_move_the_score_move_its_version(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    other = await create_venue(db_session, owner)
    author = await create_user(db_session)

    async def moved(action: object) -> bool:
        before = await _version(db_session, venue)
        await action  # type: ignore[misc]
        return await _version(db_session, venue) > before

    checkin = await post_checkin(db_session, author, venue)
    assert await _version(db_session, venue) == 1
    edit = checkin_service.update_checkin
    assert await moved(
        edit(db_session, checkin.id, current_user=author, updates={"rating_taste": 1})
    )
    assert await moved(
        edit(
            db_session,
            checkin.id,
            current_user=author,
            updates={"visibility": Visibility.PRIVATE},
        )
    )
    assert not await moved(
        edit(
            db_session, checkin.id, current_user=author, updates={"note": "only words"}
        )
    )
    assert await moved(
        checkin_service.soft_delete_checkin(db_session, checkin.id, current_user=author)
    )

    moving = await post_checkin(db_session, author, venue)
    other_before = await _version(db_session, other)
    assert await moved(
        db_session.execute(
            Checkin.__table__.update()  # pyright: ignore[reportAttributeAccessIssue]
            .where(Checkin.id == moving.id)
            .values(venue_id=other.id)
        )
    )
    assert await _version(db_session, other) > other_before


async def test_a_status_change_moves_every_venue_the_user_checked_into(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    first, second = (
        await create_venue(db_session, owner),
        await create_venue(db_session, owner),
    )
    author = await create_user(db_session)
    await post_checkin(db_session, author, first)
    await post_checkin(db_session, author, second)
    before = (await _version(db_session, first), await _version(db_session, second))

    await _set_status(db_session, author, UserStatus.FROZEN)

    after = (await _version(db_session, first), await _version(db_session, second))
    assert after[0] > before[0]
    assert after[1] > before[1]


async def test_account_deletion_moves_the_version_through_the_cascade(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    author = await create_user(db_session)
    await post_checkin(db_session, author, venue)
    before = await _version(db_session, venue)

    await set_current_user_identity(db_session, author.id)
    await db_session.execute(delete(User).where(User.id == author.id))

    assert await _version(db_session, venue) > before


async def test_the_cache_serves_the_current_version_and_misses_after_a_write(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    await _fill(db_session, venue)
    await db_session.refresh(venue)

    first = await get_venue_score(db_session, venue)
    cached = await redis_client.get(score_cache_key(venue.id, venue.score_version))
    assert cached is not None
    assert await redis_client.ttl(score_cache_key(venue.id, venue.score_version)) > 0

    author = await create_user(db_session)
    await post_checkin(db_session, author, venue)
    await db_session.refresh(venue)
    second = await get_venue_score(db_session, venue)

    assert first.checkin_count == SCORE_FLOOR
    assert second.checkin_count == SCORE_FLOOR + 1


async def test_a_new_venue_starts_at_version_zero(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)

    assert await _version(db_session, venue) == 0
