"""Integration tests for app.services.venue_report against the real
test database.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity
from app.exceptions import VenueNotFoundError, VenueReportNotFoundError
from app.models.user import User, UserRole
from app.models.venue import Venue
from app.seeds.identity import venue_category_id
from app.services import venue_report as venue_report_service

_CAFE_CATEGORY_ID = venue_category_id("cafe-general")


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


async def test_create_venue_report_persists(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    report = await venue_report_service.create_venue_report(
        db_session, reporter_id=reporter.id, venue_id=venue.id, reason="wrong_address"
    )

    assert report.venue_id == venue.id
    assert report.status == "pending"


async def test_create_venue_report_raises_when_venue_missing(
    db_session: AsyncSession,
) -> None:
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    with pytest.raises(VenueNotFoundError):
        await venue_report_service.create_venue_report(
            db_session, reporter_id=reporter.id, venue_id=uuid4(), reason="duplicate"
        )


async def test_create_venue_report_is_idempotent(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)

    first = await venue_report_service.create_venue_report(
        db_session, reporter_id=reporter.id, venue_id=venue.id, reason="wrong_address"
    )
    second = await venue_report_service.create_venue_report(
        db_session, reporter_id=reporter.id, venue_id=venue.id, reason="duplicate"
    )

    assert first.id == second.id
    assert second.reason == "wrong_address"


async def test_list_venue_reports_filters_by_status(db_session: AsyncSession) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    await venue_report_service.create_venue_report(
        db_session, reporter_id=reporter.id, venue_id=venue.id, reason="wrong_address"
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    pending = await venue_report_service.list_venue_reports(
        db_session, status="pending", limit=20, offset=0
    )
    dismissed = await venue_report_service.list_venue_reports(
        db_session, status="dismissed", limit=20, offset=0
    )

    assert any(r.venue_id == venue.id for r in pending)
    assert dismissed == []


async def test_action_venue_report_updates_status_and_resolver(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    report = await venue_report_service.create_venue_report(
        db_session, reporter_id=reporter.id, venue_id=venue.id, reason="duplicate"
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    resolved = await venue_report_service.action_venue_report(
        db_session, report.id, admin_id=admin.id
    )

    assert resolved.status == "actioned"
    assert resolved.resolved_by == admin.id


async def test_dismiss_venue_report_updates_status_and_resolver(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    venue = await _create_venue(db_session, owner)
    reporter = await _create_user(db_session)
    await set_current_user_identity(db_session, reporter.id)
    report = await venue_report_service.create_venue_report(
        db_session, reporter_id=reporter.id, venue_id=venue.id, reason="wrong_name"
    )

    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)
    resolved = await venue_report_service.dismiss_venue_report(
        db_session, report.id, admin_id=admin.id
    )

    assert resolved.status == "dismissed"
    assert resolved.resolved_by == admin.id
    assert resolved.resolved_at is not None


async def test_dismiss_venue_report_raises_when_not_found(
    db_session: AsyncSession,
) -> None:
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    await set_current_user_identity(db_session, admin.id)

    with pytest.raises(VenueReportNotFoundError):
        await venue_report_service.dismiss_venue_report(
            db_session, uuid4(), admin_id=admin.id
        )
