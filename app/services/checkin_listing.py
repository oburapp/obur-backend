"""Check-in listing: a venue's or a user's check-ins, filtered to what the
viewer is allowed to see. The query-level counterpart of
`app.core.authz.can_view`, which judges a single row instead.
"""

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import (
    account_is_visible,
    close_friend_of_owner_exists,
    is_owner_or_admin,
)
from app.core.visibility import Visibility
from app.models.checkin import Checkin
from app.models.user import User, UserRole


async def list_checkins_for_venue(
    session: AsyncSession,
    venue_id: uuid.UUID,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[Checkin]:
    """List a venue's check-ins, newest first, filtered to what `viewer`
    is allowed to see (see app.core.authz.can_view); an admin sees
    everything.
    """
    conditions = [
        Checkin.venue_id == venue_id,
        Checkin.deleted_at.is_(None),
        account_is_visible(Checkin.user_id),
    ]
    if viewer is None:
        conditions.append(Checkin.visibility == Visibility.PUBLIC)
    elif viewer.role != UserRole.ADMIN:
        conditions.append(
            or_(
                Checkin.visibility == Visibility.PUBLIC,
                Checkin.user_id == viewer.id,
                and_(
                    Checkin.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(Checkin.user_id, viewer.id),
                ),
            )
        )
    result = await session.execute(
        select(Checkin)
        .where(*conditions)
        .order_by(Checkin.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def list_checkins_for_user(
    session: AsyncSession,
    target_user_id: uuid.UUID,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[Checkin]:
    """List a user's check-ins, newest first, filtered to what `viewer`
    is allowed to see (see app.core.authz.can_view); an admin sees
    everything.
    """
    conditions = [
        Checkin.user_id == target_user_id,
        Checkin.deleted_at.is_(None),
        account_is_visible(Checkin.user_id),
    ]
    if viewer is None:
        conditions.append(Checkin.visibility == Visibility.PUBLIC)
    elif not is_owner_or_admin(target_user_id, viewer):
        conditions.append(
            or_(
                Checkin.visibility == Visibility.PUBLIC,
                and_(
                    Checkin.visibility == Visibility.CLOSE_FRIENDS,
                    close_friend_of_owner_exists(Checkin.user_id, viewer.id),
                ),
            )
        )
    result = await session.execute(
        select(Checkin)
        .where(*conditions)
        .order_by(Checkin.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
