"""Integration tests for the RLS policies themselves, on `checkins`,
`lists`, and `venue_saves` (ADR-0016 in obur-docs). Not the
identity-setting mechanism (see
test_rls_identity_mechanism_integration.py) and not `can_view` (see
test_authz.py): these exist to meet the five criteria ADR-0016 sets for
an RLS test suite that actually proves something, rather than one that's
merely green.

1. Every test here runs as the real **application role**, never the
   owner: `db_session` already connects this way
   (`app.core.database.engine` uses `app_database_url`), so nothing
   extra to arrange, but it's worth stating since it's the one criterion
   that's easy to lose silently if a fixture ever changed.
2. Both the **"can see"** case and explicitly the **"cannot see"** case
   are asserted together, never only the positive one.
3. Assertions query the database **directly** (a raw `select()`, or
   `session.get()` by id), not through `can_view` or a service function,
   so a passing test proves the policy itself, not the application code
   sitting in front of it.
4. A **parity test** simulates this project's own past failure class (a
   query that skips calling `can_view` entirely, the exact shape of the
   existence-leak and stale-visibility bugs already found here) and
   confirms RLS still blocks it independently.
5. A **fail-closed test** proves a session with no identity set sees
   only `public` rows, not everything.
"""

from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import clear_current_user_identity, set_current_user_identity
from app.core.visibility import Visibility
from app.models.checkin import Checkin
from app.models.list import List
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.models.venue_save import VenueSave
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services import close_friend as close_friend_service
from app.services import follow as follow_service
from app.services import list as list_service
from app.services import venue_save as venue_save_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")
_TZ = "Europe/Istanbul"


async def _create_user(session: AsyncSession, *, role: str = UserRole.USER) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_venue(session: AsyncSession, added_by: User) -> Venue:
    # Venue creation now requires an authenticated identity (RLS,
    # migration c1d5a8f042e7).
    await set_current_user_identity(session, added_by.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
    )
    session.add(venue)
    await session.flush()
    return venue


async def _create_checkin(
    session: AsyncSession, owner: User, venue: Venue, *, visibility: str
) -> Checkin:
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
        visibility=visibility,
    )


async def test_raw_query_sees_exactly_public_owner_and_admin_but_not_stranger(
    db_session: AsyncSession,
) -> None:
    """Criteria 2 + 3: both directions, asserted from a raw query, not
    through `can_view`.
    """
    owner = await _create_user(db_session)
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, owner.id)
    venue = await _create_venue(db_session, owner)
    public_checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.PUBLIC
    )
    private_checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.PRIVATE
    )

    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, stranger.id)
    as_stranger = (
        (
            await db_session.execute(
                select(Checkin.id).where(Checkin.user_id == owner.id)
            )
        )
        .scalars()
        .all()
    )
    assert public_checkin.id in as_stranger
    assert private_checkin.id not in as_stranger

    await set_current_user_identity(db_session, owner.id)
    as_owner = (
        (
            await db_session.execute(
                select(Checkin.id).where(Checkin.user_id == owner.id)
            )
        )
        .scalars()
        .all()
    )
    assert public_checkin.id in as_owner
    assert private_checkin.id in as_owner

    await set_current_user_identity(db_session, admin.id)
    as_admin = (
        (
            await db_session.execute(
                select(Checkin.id).where(Checkin.user_id == owner.id)
            )
        )
        .scalars()
        .all()
    )
    assert public_checkin.id in as_admin
    assert private_checkin.id in as_admin


async def test_raw_query_close_friend_sees_close_friends_checkin_stranger_doesnt(
    db_session: AsyncSession,
) -> None:
    """Criteria 2 + 3, for the `close_friends` tier specifically, the one
    that depends on `rls_is_close_friend_of` rather than a plain id match.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    close_friend = await _create_user(db_session)
    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, close_friend.id)
    await follow_service.follow_user(
        db_session, follower_id=close_friend.id, following_id=owner.id
    )
    await set_current_user_identity(db_session, owner.id)
    await close_friend_service.add_close_friend(
        db_session, user_id=owner.id, friend_id=close_friend.id
    )
    venue = await _create_venue(db_session, owner)
    checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.CLOSE_FRIENDS
    )

    # `session.get()` is deliberately not used here: it checks the
    # session's identity map before issuing any SQL, and `checkin` is
    # already in it from creating the row above, a false pass, proving
    # nothing about RLS. A `select()` always issues a real query.
    await set_current_user_identity(db_session, close_friend.id)
    visible_to_close_friend = (
        await db_session.execute(select(Checkin).where(Checkin.id == checkin.id))
    ).scalar_one_or_none()
    assert visible_to_close_friend is not None

    await set_current_user_identity(db_session, stranger.id)
    visible_to_stranger = (
        await db_session.execute(select(Checkin).where(Checkin.id == checkin.id))
    ).scalar_one_or_none()
    assert visible_to_stranger is None


async def test_raw_update_by_a_stranger_affects_zero_rows_on_a_public_checkin(
    db_session: AsyncSession,
) -> None:
    """Criteria 2 + 3, for mutation rather than visibility: being able to
    *see* a public row is not being able to *change* it. A raw UPDATE,
    not `update_checkin`, so this proves the policy, not the service's
    own `ensure_visible_and_owned` guard.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await _create_venue(db_session, owner)
    checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.PUBLIC
    )

    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, stranger.id)
    # `Checkin.__table__.update()`, the plain Core statement, not
    # `update(Checkin)`: the ORM-enabled form's default session-sync
    # strategy patches matching in-memory objects' attributes to match
    # the *attempted* values, independent of whether the database
    # actually applied them, exactly the false-pass risk this test
    # exists to avoid, found empirically when this test failed on the
    # assertion below despite `rowcount` correctly reading 0.
    # `Table.update()` isn't in SQLAlchemy's own typing stubs for
    # `FromClause`, hence the two ignores below.
    result = await db_session.execute(
        Checkin.__table__.update()  # pyright: ignore[reportAttributeAccessIssue]
        .where(Checkin.id == checkin.id)
        .values(note="hacked")
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]

    await set_current_user_identity(db_session, owner.id)
    unchanged = (
        await db_session.execute(select(Checkin).where(Checkin.id == checkin.id))
    ).scalar_one()
    assert unchanged.note != "hacked"


async def test_rls_blocks_a_query_that_forgets_to_call_can_view(
    db_session: AsyncSession,
) -> None:
    """Criterion 4, the parity/drift test: simulates this project's own
    past failure class (an existence-leak and a stale-visibility bug,
    both from a query that skipped `can_view`, see PDD §17 and
    ADR-0016's Context). A bare `session.get()` by id has zero visibility
    logic in Python, on purpose, standing in for exactly that kind of
    bug. Even so, a stranger must get nothing back for a private row,
    because the database refuses it before Python ever sees it, not
    because any application code decided to.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await _create_venue(db_session, owner)
    private_checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.PRIVATE
    )

    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, stranger.id)

    # `session.get()` deliberately not used: it checks the identity map
    # before issuing SQL, and `private_checkin` is already in it from
    # creating the row above, a false pass either way here.
    forgot_to_check_visibility = (
        await db_session.execute(
            select(Checkin).where(Checkin.id == private_checkin.id)
        )
    ).scalar_one_or_none()
    assert forgot_to_check_visibility is None


async def test_no_identity_set_only_public_checkins_are_visible(
    db_session: AsyncSession,
) -> None:
    """Criterion 5, the fail-closed default: a session that never calls
    `set_current_user_identity` (a bug that skips it, or a genuinely
    anonymous caller) must not appear to be any particular user, and
    must not see private/close-friends content just because no one is
    checking. `clear_current_user_identity` is used rather than simply
    never calling `set_current_user_identity` at all, because this
    session already created rows as `owner` above and needs to provably
    forget that, not merely never have been told.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await _create_venue(db_session, owner)
    public_checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.PUBLIC
    )
    private_checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.PRIVATE
    )
    close_friends_checkin = await _create_checkin(
        db_session, owner, venue, visibility=Visibility.CLOSE_FRIENDS
    )
    await db_session.commit()

    await clear_current_user_identity(db_session)
    visible_ids = (
        (
            await db_session.execute(
                select(Checkin.id).where(Checkin.user_id == owner.id)
            )
        )
        .scalars()
        .all()
    )

    assert public_checkin.id in visible_ids
    assert private_checkin.id not in visible_ids
    assert close_friends_checkin.id not in visible_ids


async def test_lists_select_policy_respects_visibility_raw_query(
    db_session: AsyncSession,
) -> None:
    """Confirms the shared policy pattern is actually attached to
    `lists` too, not just `checkins`, the same helper functions, but a
    separate `CREATE POLICY` per table (see migration
    b7e4f209ac31), so a copy-paste mistake on one table wouldn't show up
    testing only the other.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    public_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Herkese açık"
    )
    private_list = await list_service.create_list(
        db_session, user_id=owner.id, title="Gizli", visibility=Visibility.PRIVATE
    )

    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, stranger.id)
    visible_ids = (
        (await db_session.execute(select(List.id).where(List.user_id == owner.id)))
        .scalars()
        .all()
    )

    assert public_list.id in visible_ids
    assert private_list.id not in visible_ids


async def test_venue_saves_select_policy_respects_visibility_raw_query(
    db_session: AsyncSession,
) -> None:
    """Same confirmation as the `lists` test above, for `venue_saves`,
    whose default visibility is `private` rather than `public`
    (ADR-0006), the opposite default from the other two tables.
    """
    owner = await _create_user(db_session)
    await set_current_user_identity(db_session, owner.id)
    venue = await _create_venue(db_session, owner)
    private_save = await venue_save_service.save_venue(
        db_session, user_id=owner.id, venue_id=venue.id, type="visited"
    )
    public_save = await venue_save_service.save_venue(
        db_session,
        user_id=owner.id,
        venue_id=venue.id,
        type="wishlist",
        visibility=Visibility.PUBLIC,
    )

    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, stranger.id)
    visible_ids = (
        (
            await db_session.execute(
                select(VenueSave.id).where(VenueSave.user_id == owner.id)
            )
        )
        .scalars()
        .all()
    )

    assert public_save.id in visible_ids
    assert private_save.id not in visible_ids
