"""A profile's most-visited places (ADR-0020 in obur-docs): the five
venues a user checked into most often, ties broken by the most recent
visit.

The list has its own visibility setting (`User.most_visited_visibility`,
private by default). Counts depend on who is looking: the owner, and an
admin, count every non-deleted check-in, private ones included; anyone
else counts only check-ins they could see themselves (`public`, plus
`close_friends` for someone on the owner's close friends list), so a
private check-in is never revealed through a count. A viewer the list
isn't shown to gets an empty list, the same answer as a user with no
check-ins, so the setting itself isn't revealed either.
"""

import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import (
    account_is_visible,
    is_blocked_between,
    is_close_friend,
    is_owner_or_admin,
)
from app.core.visibility import Visibility
from app.models.checkin import Checkin
from app.models.user import User
from app.models.venue import Venue
from app.schemas.most_visited import MostVisitedVenue

MOST_VISITED_LIMIT = 5


async def _countable(
    session: AsyncSession, owner: User, viewer: User | None
) -> ColumnElement[bool] | None:
    """Which of `owner`'s check-ins `viewer` may count, or None when the
    list isn't shown to them at all.
    """
    if viewer is not None and is_owner_or_admin(owner.id, viewer):
        return Checkin.id.is_not(None)
    visibility = owner.most_visited_visibility
    if visibility == Visibility.PRIVATE:
        return None
    friend = viewer is not None and await is_close_friend(
        session, owner_id=owner.id, viewer_id=viewer.id
    )
    if visibility == Visibility.CLOSE_FRIENDS and not friend:
        return None
    if friend:
        return Checkin.visibility.in_([Visibility.PUBLIC, Visibility.CLOSE_FRIENDS])
    return Checkin.visibility == Visibility.PUBLIC


async def list_most_visited(
    session: AsyncSession, owner_id: uuid.UUID, *, viewer: User | None
) -> list[MostVisitedVenue]:
    """`owner_id`'s most-visited venues as `viewer` may see them."""
    owner = await session.scalar(
        select(User).where(User.id == owner_id, account_is_visible(User.id))
    )
    if owner is None:
        return []
    # RLS already hides a blocked pair's rows from each other; checked here
    # too so the application never depends on that alone.
    if viewer is not None and await is_blocked_between(session, owner.id, viewer.id):
        return []
    countable = await _countable(session, owner, viewer)
    if countable is None:
        return []
    visits = func.count(Checkin.id)
    result = await session.execute(
        select(Venue.id, Venue.name, Venue.category_id, visits.label("visit_count"))
        .join(Checkin, Checkin.venue_id == Venue.id)
        .where(Checkin.user_id == owner.id, Checkin.deleted_at.is_(None), countable)
        .group_by(Venue.id)
        .order_by(visits.desc(), func.max(Checkin.visited_at).desc(), Venue.id)
        .limit(MOST_VISITED_LIMIT)
    )
    return [
        MostVisitedVenue(
            venue_id=row.id,
            name=row.name,
            category_id=row.category_id,
            visit_count=row.visit_count,
        )
        for row in result
    ]
