"""Integration tests for Phase 10's blocking/muting RLS (ADR-0010 in
obur-docs, PDD §11), migration 190c719287e2. Same five criteria
`test_rls_policies_integration.py`'s own module docstring sets: real
application role, both directions asserted together, raw queries only
(never through a service or `can_view`, which doesn't have its blocking
dimension yet, see docs/roadmap.md Phase 10), a parity test where one
exists, and a fail-closed default.

`blocks`' own access control (Option B, ADR-0010) is the one genuinely
new shape here: unlike every other relationship table in this project,
the blocked person's session can never see the row naming them at all,
not even the direction. That's asserted directly below, separately from
whether blocking actually *works* as an enforcement mechanism elsewhere.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.models.block import Block
from app.models.checkin import Checkin
from app.models.content_report import ContentReport
from app.models.mute import Mute
from app.models.notification import (
    Notification,
    NotificationTargetType,
    NotificationType,
)
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.models.venue_report import VenueReport
from app.seeds.identity import venue_category_id
from app.services import checkin as checkin_service
from app.services.notification import create_notification

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
    await set_current_user_identity(session, added_by.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=added_by.id,
        district="Kadıköy",
    )
    session.add(venue)
    await session.flush()
    return venue


async def _create_public_checkin(
    session: AsyncSession, owner: User, venue: Venue
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
        visibility=Visibility.PUBLIC,
    )


async def _block(session: AsyncSession, *, blocker: User, blocked: User) -> None:
    """Raw insert as the blocker, matching how the real endpoint will
    eventually create the row: this module tests RLS, not
    `app.services.block` (Part 2).
    """
    await set_current_user_identity(session, blocker.id)
    await session.execute(
        Block.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            blocker_id=blocker.id, blocked_id=blocked.id
        )
    )


# --- blocks: Option B's own access control ---------------------------------


async def test_blocker_sees_own_block_blocked_person_never_does(
    db_session: AsyncSession,
) -> None:
    """Criteria 2 + 3: the one property that makes Option B what it is.
    Not "hidden by default", `blocked_id` never satisfies the SELECT
    policy at all, in either raw form (a full row select or a targeted
    lookup by the composite key).
    """
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await _block(db_session, blocker=blocker, blocked=blocked)

    await set_current_user_identity(db_session, blocker.id)
    as_blocker = (
        await db_session.execute(select(Block).where(Block.blocked_id == blocked.id))
    ).scalar_one_or_none()
    assert as_blocker is not None

    await set_current_user_identity(db_session, blocked.id)
    as_blocked = (
        await db_session.execute(select(Block).where(Block.blocker_id == blocker.id))
    ).scalar_one_or_none()
    assert as_blocked is None


async def test_admin_sees_any_block_row(db_session: AsyncSession) -> None:
    """Criterion 3: admin moderation access is never affected by a block
    between two other users (PDD §11), which must hold for `blocks`
    itself, not only for the content it protects.
    """
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await _block(db_session, blocker=blocker, blocked=blocked)

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    as_admin = (
        await db_session.execute(
            select(Block).where(
                Block.blocker_id == blocker.id, Block.blocked_id == blocked.id
            )
        )
    ).scalar_one_or_none()
    assert as_admin is not None


async def test_blocks_insert_policy_rejects_blocking_on_someone_elses_behalf(
    db_session: AsyncSession,
) -> None:
    """A stranger cannot forge `blocker_id` to be someone other than
    themselves, the same ownership check every directional relationship
    table (`follows`, `mutes`) already enforces on insert.
    """
    impersonator = await _create_user(db_session)
    real_blocker = await _create_user(db_session)
    target = await _create_user(db_session)
    await set_current_user_identity(db_session, impersonator.id)

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with db_session.begin_nested():
            await db_session.execute(
                Block.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
                    blocker_id=real_blocker.id, blocked_id=target.id
                )
            )


async def test_blocks_delete_policy_rejects_the_blocked_person_unblocking_themselves(
    db_session: AsyncSession,
) -> None:
    """`blocks_delete` is blocker-only, not permissive on `blocked_id`
    the way `follows_delete`/`close_friends_delete` are on their second
    column: PDD §11 makes unblocking the blocker's action alone, and
    unlike those two tables nothing ever needs the blocked person to end
    the relationship themselves. A raw `DELETE`, proving the policy
    itself would refuse this even if a future code path ever tried.
    """
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await _block(db_session, blocker=blocker, blocked=blocked)

    await set_current_user_identity(db_session, blocked.id)
    result = await db_session.execute(
        Block.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            Block.blocker_id == blocker.id, Block.blocked_id == blocked.id
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_blocked_persons_real_account_deletion_still_cascades_the_block_away(
    db_session: AsyncSession,
) -> None:
    """The test above proves `blocks_delete` correctly refuses the
    blocked person's own *explicit* delete. This proves that refusal
    doesn't also break real account-deletion cleanup: a genuine `DELETE
    FROM users` for the blocked person's own account, not a simulation.
    PostgreSQL's referential integrity checks always bypass row security
    ("Row Security Policies" in the manual), so `ON DELETE CASCADE`
    reaches this row regardless of what `blocks_delete` says, run as
    whichever identity the account-deletion endpoint will eventually use.
    """
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await _block(db_session, blocker=blocker, blocked=blocked)

    await set_current_user_identity(db_session, blocked.id)
    await db_session.execute(
        User.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            User.id == blocked.id
        )
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    remaining = (
        await db_session.execute(select(Block).where(Block.blocker_id == blocker.id))
    ).scalar_one_or_none()
    assert remaining is None


# --- blocking enforcement propagating into existing tables ------------------


async def test_block_hides_a_public_checkin_from_the_blocked_viewer_and_back(
    db_session: AsyncSession,
) -> None:
    """Criterion 2, both directions: `rls_can_view_visibility`'s new
    guard must hide the blocker's content from the blocked viewer *and*
    the blocked person's content from the blocker, from one block row,
    since enforcement is bidirectional even though the row is directional
    (PDD §11, ADR-0010).
    """
    owner = await _create_user(db_session)
    viewer = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    owner_checkin = await _create_public_checkin(db_session, owner, venue)
    await set_current_user_identity(db_session, viewer.id)
    viewer_checkin = await _create_public_checkin(db_session, viewer, venue)

    await _block(db_session, blocker=owner, blocked=viewer)

    await set_current_user_identity(db_session, viewer.id)
    owner_checkin_visible_to_viewer = (
        await db_session.execute(select(Checkin).where(Checkin.id == owner_checkin.id))
    ).scalar_one_or_none()
    assert owner_checkin_visible_to_viewer is None

    await set_current_user_identity(db_session, owner.id)
    viewer_checkin_visible_to_owner = (
        await db_session.execute(select(Checkin).where(Checkin.id == viewer_checkin.id))
    ).scalar_one_or_none()
    assert viewer_checkin_visible_to_owner is None


async def test_block_does_not_hide_content_from_admin_or_from_the_owner_themselves(
    db_session: AsyncSession,
) -> None:
    """The owner still sees their own checkin regardless (a block cannot
    exist between an account and itself), and admin moderation access is
    never affected by a block between two other users (PDD §11).
    """
    owner = await _create_user(db_session)
    viewer = await _create_user(db_session)
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    venue = await _create_venue(db_session, owner)
    await set_current_user_identity(db_session, owner.id)
    checkin = await _create_public_checkin(db_session, owner, venue)

    await _block(db_session, blocker=owner, blocked=viewer)

    await set_current_user_identity(db_session, owner.id)
    visible_to_owner = (
        await db_session.execute(select(Checkin).where(Checkin.id == checkin.id))
    ).scalar_one_or_none()
    assert visible_to_owner is not None

    await set_current_user_identity(db_session, admin.id)
    visible_to_admin = (
        await db_session.execute(select(Checkin).where(Checkin.id == checkin.id))
    ).scalar_one_or_none()
    assert visible_to_admin is not None


async def test_block_hides_each_persons_profile_from_the_other_via_plain_query(
    db_session: AsyncSession,
) -> None:
    """`users_select` treats both profiles as nonexistent to each other,
    fully symmetric, per PDD §11's "a blocked profile behaves exactly
    like a nonexistent one". No exception for the blocker either: a
    plain query is not how a blocker sees who they've blocked, that
    goes through the narrow `rls_list_blocked_users` function instead
    (migration `f1d017015e34`, tested against the real service in
    tests/integration/test_block_integration.py), which never widens
    `users_select` itself.
    """
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await _block(db_session, blocker=blocker, blocked=blocked)

    await set_current_user_identity(db_session, blocked.id)
    blocker_profile_visible_to_blocked = (
        await db_session.execute(select(User).where(User.id == blocker.id))
    ).scalar_one_or_none()
    assert blocker_profile_visible_to_blocked is None

    await set_current_user_identity(db_session, blocker.id)
    blocked_profile_visible_to_blocker = (
        await db_session.execute(select(User).where(User.id == blocked.id))
    ).scalar_one_or_none()
    assert blocked_profile_visible_to_blocker is None


async def test_no_identity_set_still_sees_every_profile(
    db_session: AsyncSession,
) -> None:
    """Fail-closed in the opposite sense here: `users_select` must stay
    fully open with no identity set at all (identity resolution itself
    depends on this, see migration e4f8b21ac930), not accidentally start
    hiding everyone because `rls_current_user_id()` is `NULL`.
    """
    blocker = await _create_user(db_session)
    blocked = await _create_user(db_session)
    await _block(db_session, blocker=blocker, blocked=blocked)

    from app.core.database import clear_current_user_identity

    await clear_current_user_identity(db_session)
    both_visible = (
        (
            await db_session.execute(
                select(User.id).where(User.id.in_([blocker.id, blocked.id]))
            )
        )
        .scalars()
        .all()
    )
    assert set(both_visible) == {blocker.id, blocked.id}


async def test_notifications_insert_policy_rejects_notifying_across_an_active_block(
    db_session: AsyncSession,
) -> None:
    """Forward-looking backstop: even if a future notification-service
    bug tried to notify across an active block, the database refuses the
    insert outright.
    """
    owner = await _create_user(db_session)
    actor = await _create_user(db_session)
    await _block(db_session, blocker=owner, blocked=actor)

    await set_current_user_identity(db_session, actor.id)
    with pytest.raises(ProgrammingError, match="row-level security"):
        async with db_session.begin_nested():
            await create_notification(
                db_session,
                user_id=owner.id,
                type=NotificationType.CHECKIN_LIKE,
                actor_id=actor.id,
                target_type=NotificationTargetType.CHECKIN,
                target_id=uuid4(),
            )


async def test_notifications_select_hides_a_notification_between_a_blocked_pair(
    db_session: AsyncSession,
) -> None:
    """The retroactive purge itself is Part 2's service-layer work; this
    is the RLS-layer backstop underneath it, proven directly against a
    notification created *before* the block (raw insert, bypassing
    `notifications_insert`'s own new guard, standing in for a row the
    purge hasn't reached yet).
    """
    owner = await _create_user(db_session)
    actor = await _create_user(db_session)
    await set_current_user_identity(db_session, actor.id)
    notification = await create_notification(
        db_session,
        user_id=owner.id,
        type=NotificationType.CHECKIN_LIKE,
        actor_id=actor.id,
        target_type=NotificationTargetType.CHECKIN,
        target_id=uuid4(),
    )

    await _block(db_session, blocker=owner, blocked=actor)

    await set_current_user_identity(db_session, owner.id)
    visible_to_owner = (
        await db_session.execute(
            select(Notification).where(Notification.id == notification.id)
        )
    ).scalar_one_or_none()
    assert visible_to_owner is None

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    visible_to_admin = (
        await db_session.execute(
            select(Notification).where(Notification.id == notification.id)
        )
    ).scalar_one_or_none()
    assert visible_to_admin is not None


# --- mutes: muter-only, no bypass function needed ---------------------------


async def test_muter_sees_own_mute_muted_person_never_does(
    db_session: AsyncSession,
) -> None:
    """Same shape as `blocks`' own access control, and for a related but
    distinct reason: mute is meant to be silent (PDD §11), so the muted
    person's session must never confirm it exists either.
    """
    muter = await _create_user(db_session)
    muted = await _create_user(db_session)
    await set_current_user_identity(db_session, muter.id)
    await db_session.execute(
        Mute.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            user_id=muter.id, muted_id=muted.id
        )
    )

    as_muter = (
        await db_session.execute(select(Mute).where(Mute.muted_id == muted.id))
    ).scalar_one_or_none()
    assert as_muter is not None

    await set_current_user_identity(db_session, muted.id)
    as_muted = (
        await db_session.execute(select(Mute).where(Mute.user_id == muter.id))
    ).scalar_one_or_none()
    assert as_muted is None


async def test_mutes_delete_policy_rejects_the_muted_person_removing_it(
    db_session: AsyncSession,
) -> None:
    """Same reasoning as `blocks_delete`: muter-only, the muted person
    has no legitimate reason to ever remove a mute they're not even
    supposed to know about.
    """
    muter = await _create_user(db_session)
    muted = await _create_user(db_session)
    await set_current_user_identity(db_session, muter.id)
    await db_session.execute(
        Mute.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            user_id=muter.id, muted_id=muted.id
        )
    )

    await set_current_user_identity(db_session, muted.id)
    result = await db_session.execute(
        Mute.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            Mute.user_id == muter.id, Mute.muted_id == muted.id
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_muted_persons_real_account_deletion_still_cascades_the_mute_away(
    db_session: AsyncSession,
) -> None:
    """Same proof as the `blocks` cascade test above, for `mutes`: a
    genuine `DELETE FROM users` for the muted person's own account still
    clears the row, since referential integrity checks always bypass row
    security regardless of `mutes_delete`.
    """
    muter = await _create_user(db_session)
    muted = await _create_user(db_session)
    await set_current_user_identity(db_session, muter.id)
    await db_session.execute(
        Mute.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            user_id=muter.id, muted_id=muted.id
        )
    )

    await set_current_user_identity(db_session, muted.id)
    await db_session.execute(
        User.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            User.id == muted.id
        )
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    remaining = (
        await db_session.execute(select(Mute).where(Mute.user_id == muter.id))
    ).scalar_one_or_none()
    assert remaining is None


# --- content_reports / venue_reports: reporter-or-admin, no delete ----------


async def test_content_report_visible_to_reporter_and_admin_not_to_a_stranger(
    db_session: AsyncSession,
) -> None:
    reporter = await _create_user(db_session)
    reported = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    await db_session.execute(
        ContentReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            id=uuid4(),
            reporter_id=reporter.id,
            target_type="user",
            target_id=reported.id,
            reason="harassment",
        )
    )

    as_reporter = (
        await db_session.execute(
            select(ContentReport).where(ContentReport.target_id == reported.id)
        )
    ).scalar_one_or_none()
    assert as_reporter is not None

    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, stranger.id)
    as_stranger = (
        await db_session.execute(
            select(ContentReport).where(ContentReport.target_id == reported.id)
        )
    ).scalar_one_or_none()
    assert as_stranger is None

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    as_admin = (
        await db_session.execute(
            select(ContentReport).where(ContentReport.target_id == reported.id)
        )
    ).scalar_one_or_none()
    assert as_admin is not None


async def test_content_reports_insert_policy_rejects_forging_the_reporter(
    db_session: AsyncSession,
) -> None:
    impersonator = await _create_user(db_session)
    real_reporter = await _create_user(db_session)
    reported = await _create_user(db_session)
    await set_current_user_identity(db_session, impersonator.id)

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with db_session.begin_nested():
            await db_session.execute(
                ContentReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
                    id=uuid4(),
                    reporter_id=real_reporter.id,
                    target_type="user",
                    target_id=reported.id,
                    reason="spam",
                )
            )


async def test_content_reports_update_policy_rejects_a_non_admin_resolving_it(
    db_session: AsyncSession,
) -> None:
    """A raw `UPDATE`, proving the policy itself: only an admin may
    resolve a report, not even the reporter who filed it.
    """
    reporter = await _create_user(db_session)
    reported = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    await db_session.execute(
        ContentReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            id=uuid4(),
            reporter_id=reporter.id,
            target_type="user",
            target_id=reported.id,
            reason="spam",
        )
    )

    result = await db_session.execute(
        ContentReport.__table__.update()  # pyright: ignore[reportAttributeAccessIssue]
        .where(ContentReport.target_id == reported.id)
        .values(status="dismissed")
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_content_reports_have_no_delete_policy_at_all(
    db_session: AsyncSession,
) -> None:
    """Reports are a permanent moderation record: no policy for `DELETE`
    means deny by default, the same "should never be written to outside
    its sanctioned path" choice `venue_categories` already made
    (migration c1d5a8f042e7), so even an admin's raw `DELETE` affects
    zero rows.
    """
    reporter = await _create_user(db_session)
    reported = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    await db_session.execute(
        ContentReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            id=uuid4(),
            reporter_id=reporter.id,
            target_type="user",
            target_id=reported.id,
            reason="spam",
        )
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    result = await db_session.execute(
        ContentReport.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            ContentReport.target_id == reported.id
        )
    )
    assert result.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]


async def test_venue_report_visible_to_reporter_and_admin_not_to_a_stranger(
    db_session: AsyncSession,
) -> None:
    """Same shape as `content_reports`, `venue_reports` this time, a
    copy-paste mistake on one wouldn't show up testing only the other.
    """
    reporter = await _create_user(db_session)
    venue = await _create_venue(db_session, reporter)
    await set_current_user_identity(db_session, reporter.id)
    await db_session.execute(
        VenueReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            id=uuid4(),
            reporter_id=reporter.id,
            venue_id=venue.id,
            reason="wrong_address",
        )
    )

    as_reporter = (
        await db_session.execute(
            select(VenueReport).where(VenueReport.venue_id == venue.id)
        )
    ).scalar_one_or_none()
    assert as_reporter is not None

    stranger = await _create_user(db_session)
    await set_current_user_identity(db_session, stranger.id)
    as_stranger = (
        await db_session.execute(
            select(VenueReport).where(VenueReport.venue_id == venue.id)
        )
    ).scalar_one_or_none()
    assert as_stranger is None


# --- reason 'other' requires details, on both report tables ----------------


async def test_content_report_reason_other_without_details_is_rejected(
    db_session: AsyncSession,
) -> None:
    """`ck_content_reports_details_required_for_other`: a fixed reason
    vocabulary can't cover everything, so `other` needs the reporter to
    actually say what's wrong, checked at the database layer, not only
    whatever a request schema enforces later.
    """
    reporter = await _create_user(db_session)
    reported = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                ContentReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
                    id=uuid4(),
                    reporter_id=reporter.id,
                    target_type="user",
                    target_id=reported.id,
                    reason="other",
                )
            )


async def test_content_report_reason_other_with_details_succeeds(
    db_session: AsyncSession,
) -> None:
    reporter = await _create_user(db_session)
    reported = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    await db_session.execute(
        ContentReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
            id=uuid4(),
            reporter_id=reporter.id,
            target_type="user",
            target_id=reported.id,
            reason="other",
            details="Sürekli sahte hesaplarla mesaj atıyor.",
        )
    )

    saved = (
        await db_session.execute(
            select(ContentReport).where(ContentReport.target_id == reported.id)
        )
    ).scalar_one()
    assert saved.details == "Sürekli sahte hesaplarla mesaj atıyor."


async def test_venue_report_reason_other_without_details_is_rejected(
    db_session: AsyncSession,
) -> None:
    """Same constraint, `venue_reports` this time, its own `CHECK`, a
    copy-paste mistake on one wouldn't show up testing only the other.
    """
    reporter = await _create_user(db_session)
    venue = await _create_venue(db_session, reporter)
    await set_current_user_identity(db_session, reporter.id)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                VenueReport.__table__.insert().values(  # pyright: ignore[reportAttributeAccessIssue]
                    id=uuid4(),
                    reporter_id=reporter.id,
                    venue_id=venue.id,
                    reason="other",
                )
            )
