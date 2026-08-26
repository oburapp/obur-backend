"""Integration tests for app.services.content_report against the real
test database. Idempotency, the reason/details CHECK, and the target
existence/visibility check all depend on real DB state.
"""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.core.visibility import Visibility
from app.exceptions import CheckinNotFoundError, ContentReportNotFoundError
from app.models.checkin import Checkin
from app.models.content_report import ContentReportTargetType
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import block as block_service
from app.services import checkin as checkin_service
from app.services import content_report as content_report_service

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


async def _create_checkin(
    session: AsyncSession, owner: User, *, visibility: str = Visibility.PUBLIC
) -> Checkin:
    await set_current_user_identity(session, owner.id)
    venue = Venue(
        name="Kahveci",
        lat=41.0,
        lng=29.0,
        category_id=_CAFE_CATEGORY_ID,
        added_by=owner.id,
        district="Kadıköy",
    )
    session.add(venue)
    await session.flush()
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


async def test_create_content_report_on_a_checkin_persists(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    report = await content_report_service.create_content_report(
        db_session,
        reporter=reporter,
        target_type=ContentReportTargetType.CHECKIN,
        target_id=checkin.id,
        reason="spam",
    )

    assert report.target_id == checkin.id
    assert report.status == "pending"


async def test_create_content_report_on_a_checkin_raises_when_not_visible(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner, visibility=Visibility.PRIVATE)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    with pytest.raises(CheckinNotFoundError):
        await content_report_service.create_content_report(
            db_session,
            reporter=reporter,
            target_type=ContentReportTargetType.CHECKIN,
            target_id=checkin.id,
            reason="spam",
        )


async def test_create_content_report_on_a_checkin_is_idempotent(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    first = await content_report_service.create_content_report(
        db_session,
        reporter=reporter,
        target_type=ContentReportTargetType.CHECKIN,
        target_id=checkin.id,
        reason="spam",
    )
    second = await content_report_service.create_content_report(
        db_session,
        reporter=reporter,
        target_type=ContentReportTargetType.CHECKIN,
        target_id=checkin.id,
        reason="harassment",
    )

    assert first.id == second.id
    assert second.reason == "spam"


async def test_create_content_report_on_a_user_works_even_after_being_blocked(
    db_session: AsyncSession,
) -> None:
    """The one case this service's own visibility policy is deliberately
    asymmetric for: `reported` blocking `reporter` must not stop
    `reporter` from reporting them (PDD §11, module docstring).
    """
    reporter = await _create_user(db_session)
    reported = await _create_user(db_session)
    await set_current_user_identity(db_session, reported.id)
    await block_service.create_block(
        db_session, blocker_id=reported.id, blocked_id=reporter.id
    )

    await set_current_user_identity(db_session, reporter.id)
    report = await content_report_service.create_content_report(
        db_session,
        reporter=reporter,
        target_type=ContentReportTargetType.USER,
        target_id=reported.id,
        reason="harassment",
    )

    assert report.target_id == reported.id


async def test_list_content_reports_filters_by_status(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    await content_report_service.create_content_report(
        db_session,
        reporter=reporter,
        target_type=ContentReportTargetType.CHECKIN,
        target_id=checkin.id,
        reason="spam",
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    pending = await content_report_service.list_content_reports(
        db_session, status="pending", limit=20, offset=0
    )
    dismissed = await content_report_service.list_content_reports(
        db_session, status="dismissed", limit=20, offset=0
    )

    assert any(r.target_id == checkin.id for r in pending)
    assert dismissed == []


async def test_dismiss_content_report_updates_status_and_resolver(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    checkin = await _create_checkin(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    report = await content_report_service.create_content_report(
        db_session,
        reporter=reporter,
        target_type=ContentReportTargetType.CHECKIN,
        target_id=checkin.id,
        reason="spam",
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    resolved = await content_report_service.dismiss_content_report(
        db_session, report.id, admin_id=admin.id
    )

    assert resolved.status == "dismissed"
    assert resolved.resolved_by == admin.id
    assert resolved.resolved_at is not None


async def test_action_content_report_raises_when_not_found(
    db_session: AsyncSession,
) -> None:
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)

    with pytest.raises(ContentReportNotFoundError):
        await content_report_service.action_content_report(
            db_session, uuid4(), admin_id=admin.id
        )
