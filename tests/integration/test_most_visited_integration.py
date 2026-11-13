"""Integration tests for a profile's most-visited places (ADR-0020 in
obur-docs): the list's own visibility setting, and counts that depend on
who is looking, so a private check-in is never revealed through a count.
"""

from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.models.user import User
from app.models.venue import Venue
from app.services import block as block_service
from app.services import checkin as checkin_service
from app.services.most_visited import MOST_VISITED_LIMIT, list_most_visited
from tests.integration.tagging_factories import (
    add_close_friend,
    befriend,
    create_user,
    create_venue,
    post_checkin,
)

_TZ = "Europe/Istanbul"


async def _visits(
    session: AsyncSession,
    owner: User,
    venue: Venue,
    count: int,
    visibility: str = Visibility.PUBLIC,
) -> None:
    for _ in range(count):
        await post_checkin(session, owner, venue, visibility=visibility)


async def _counts(
    session: AsyncSession, owner: User, viewer: User | None
) -> dict[UUID, int]:
    if viewer is not None:
        await set_current_user_identity(session, viewer.id)
    places = await list_most_visited(session, owner.id, viewer=viewer)
    return {place.venue_id: place.visit_count for place in places}


async def _share(session: AsyncSession, owner: User, visibility: str) -> None:
    await set_current_user_identity(session, owner.id)
    owner.most_visited_visibility = visibility
    await session.flush()


async def test_the_owner_counts_private_checkins_others_do_not(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    develi, petra = (
        await create_venue(db_session, owner),
        await create_venue(db_session, owner),
    )
    await _visits(db_session, owner, develi, 8, Visibility.PRIVATE)
    await _visits(db_session, owner, petra, 3)
    await _share(db_session, owner, Visibility.PUBLIC)
    stranger = await create_user(db_session)

    assert await _counts(db_session, owner, owner) == {develi.id: 8, petra.id: 3}
    assert await _counts(db_session, owner, stranger) == {petra.id: 3}
    assert await _counts(db_session, owner, None) == {petra.id: 3}


async def test_a_close_friend_also_counts_close_friends_checkins(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    friend = await create_user(db_session)
    await befriend(db_session, owner, friend)
    await add_close_friend(db_session, owner, friend)
    await _visits(db_session, owner, venue, 2)
    await _visits(db_session, owner, venue, 3, Visibility.CLOSE_FRIENDS)
    await _share(db_session, owner, Visibility.PUBLIC)

    assert await _counts(db_session, owner, friend) == {venue.id: 5}


async def test_a_private_list_is_empty_for_everyone_but_the_owner(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    await _visits(db_session, owner, venue, 2)
    stranger = await create_user(db_session)

    assert await _counts(db_session, owner, stranger) == {}
    assert await _counts(db_session, owner, owner) == {venue.id: 2}


async def test_a_close_friends_list_shows_only_to_close_friends(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    friend, stranger = await create_user(db_session), await create_user(db_session)
    await befriend(db_session, owner, friend)
    await add_close_friend(db_session, owner, friend)
    await _visits(db_session, owner, venue, 2)
    await _share(db_session, owner, Visibility.CLOSE_FRIENDS)

    assert await _counts(db_session, owner, friend) == {venue.id: 2}
    assert await _counts(db_session, owner, stranger) == {}


async def test_ties_go_to_the_most_recent_visit_and_the_list_stops_at_five(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venues = [
        await create_venue(db_session, owner) for _ in range(MOST_VISITED_LIMIT + 1)
    ]
    for days_ago, venue in enumerate(venues):
        await set_current_user_identity(db_session, owner.id)
        await checkin_service.create_checkin(
            db_session,
            user_id=owner.id,
            idempotency_key=uuid4(),
            venue_id=venue.id,
            rating_taste=4,
            rating_service=3,
            rating_ambiance=3,
            rating_value=2,
            visited_at=date.today() - timedelta(days=days_ago),
            visited_tz=_TZ,
        )

    places = await list_most_visited(db_session, owner.id, viewer=owner)

    assert [place.venue_id for place in places] == [
        v.id for v in venues[:MOST_VISITED_LIMIT]
    ]


async def test_deleted_checkins_and_blocked_viewers_get_nothing_extra(
    db_session: AsyncSession,
) -> None:
    owner = await create_user(db_session)
    venue = await create_venue(db_session, owner)
    checkin = await post_checkin(db_session, owner, venue)
    await _visits(db_session, owner, venue, 1)
    await checkin_service.soft_delete_checkin(
        db_session, checkin.id, current_user=owner
    )
    await _share(db_session, owner, Visibility.PUBLIC)
    blocked = await create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    await block_service.create_block(
        db_session, blocker_id=owner.id, blocked_id=blocked.id
    )

    assert await _counts(db_session, owner, owner) == {venue.id: 1}
    assert await _counts(db_session, owner, blocked) == {}
