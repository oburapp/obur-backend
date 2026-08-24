"""Account lifecycle against a real database: the delete cascade, and the
visibility of frozen accounts.

Both are things a mock can't prove. The cascade lives on the foreign keys
themselves rather than in application code, so only a real `DELETE` shows
whether it actually reaches everything; and the frozen-account filter is a
correlated subquery whose correctness is a property of the SQL.
"""

from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.models.checkin import Checkin
from app.models.follow import Follow
from app.models.list import List
from app.models.user import User, UserRole, UserStatus
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services import follow as follow_service
from app.services import list as list_service
from app.services import user as user_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_TZ = "Europe/Istanbul"


async def _create_user(session: AsyncSession, **overrides: object) -> User:
    defaults: dict[str, object] = {
        "auth_provider": "clerk",
        "auth_provider_id": f"user_{uuid4()}",
        "username": f"u{uuid4().hex[:12]}",
        "display_name": "Test User",
    }
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    await session.flush()
    return user


async def _create_venue(session: AsyncSession, owner: User) -> Venue:
    # Venue creation now requires an authenticated identity (RLS,
    # migration c1d5a8f042e7).
    await set_current_user_identity(session, owner.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def _create_checkin(session: AsyncSession, owner: User, venue: Venue) -> Checkin:
    return await checkin_service.create_checkin(
        session,
        user_id=owner.id,
        venue_id=venue.id,
        rating_taste=4,
        rating_service=3,
        rating_ambiance=3,
        rating_value=2,
        visited_at=date.today(),
        visited_tz=_TZ,
    )


async def test_deleting_an_account_purges_its_content(
    db_session: AsyncSession,
) -> None:
    """The Clerk `user.deleted` webhook used to fail here: no foreign key
    referencing `users.id` declared an `ondelete`, so deleting a user who
    had ever created anything raised a foreign-key violation.
    """
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await _create_checkin(db_session, owner, venue)
    created_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Kahveciler"
    )

    await user_service.delete_account(db_session, user_id=owner.id)

    for model, row_id in ((Checkin, checkin.id), (List, created_list.id)):
        result = await db_session.execute(select(model).where(model.id == row_id))
        assert result.scalars().all() == [], model.__name__


async def test_deleting_an_account_keeps_the_venues_it_added(
    db_session: AsyncSession,
) -> None:
    """A venue is a shared resource other users rely on, not personal
    content — it outlives the account and only loses the attribution.
    """
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)

    await user_service.delete_account(db_session, user_id=owner.id)

    # The SET NULL happens in the database, so the identity map still holds
    # the pre-delete row. `populate_existing` overwrites it from this query
    # rather than leaving the assertion to read a stale object and pass for
    # the wrong reason.
    result = await db_session.execute(
        select(Venue)
        .where(Venue.id == venue.id)
        .execution_options(populate_existing=True)
    )
    survivor = result.scalar_one()
    assert survivor.added_by is None


async def test_a_frozen_users_checkins_drop_out_of_a_venue_listing(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    viewer = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    await _create_checkin(db_session, owner, venue)

    before = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=viewer, limit=20, offset=0
    )
    assert len(before) == 1

    await user_service.freeze_account(db_session, user=owner)

    after = await checkin_service.list_checkins_for_venue(
        db_session, venue.id, viewer=viewer, limit=20, offset=0
    )
    assert after == []


async def test_a_suspended_user_drops_out_of_a_followers_listing(
    db_session: AsyncSession,
) -> None:
    target = await _create_user(db_session)
    follower = await _create_user(db_session)
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, follower.id)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=target.id
    )

    before = await follow_service.list_followers(
        db_session, target.id, limit=20, offset=0
    )
    assert [user.id for user in before] == [follower.id]

    # Suspension is admin-only (app/models/user.py's own UserStatus
    # docstring), never self-service, so this uses admin's identity, not
    # follower's own.
    await set_current_user_identity(db_session, admin.id)
    follower.status = UserStatus.SUSPENDED
    await db_session.commit()

    after = await follow_service.list_followers(
        db_session, target.id, limit=20, offset=0
    )
    assert after == []


async def test_the_follow_row_survives_a_suspension(
    db_session: AsyncSession,
) -> None:
    """Suspension hides an account, it doesn't unwind their relationships —
    that is blocking's job (PDD §11), and the follow must come back intact
    if the suspension is lifted.
    """
    target = await _create_user(db_session)
    follower = await _create_user(db_session)
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, follower.id)
    await follow_service.follow_user(
        db_session, follower_id=follower.id, following_id=target.id
    )

    await set_current_user_identity(db_session, admin.id)
    follower.status = UserStatus.SUSPENDED
    await db_session.commit()

    result = await db_session.execute(
        select(Follow).where(
            Follow.follower_id == follower.id, Follow.following_id == target.id
        )
    )
    assert result.scalar_one_or_none() is not None
