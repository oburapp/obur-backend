"""ContentReport domain: interpersonal-safety reports against a
check-in or a user profile (see ADR-0010 in obur-docs, PDD §11).

Reporting a check-in resolves it through `app.services.checkin.get_checkin`
first, the same "you must be able to see it to act on it" rule
likes and bookmarks already enforce, so a private check-in can't be
reported by someone who never had visibility into it.

Reporting a *user* deliberately skips an equivalent existence check.
`target_id` isn't a real foreign key (ADR-0010 already accepts a report
outliving or outrunning its target), and `users_select`'s blocking
guard would make the check actively harmful here: a `session.get(User,
target_id)` as the reporter would come back empty the moment the
*reported* person has blocked the *reporter*, since a block hides each
profile from the other. That's exactly the one case reporting has to
keep working, PDD §11 expects a reported user to be blockable
immediately, and a report is very often filed on the way to blocking
someone, not after.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.report_status import ReportStatus
from app.exceptions import ContentReportNotFoundError
from app.models.content_report import ContentReport
from app.models.user import User
from app.services import checkin as checkin_service


async def create_content_report(
    session: AsyncSession,
    *,
    reporter: User,
    target_type: str,
    target_id: uuid.UUID,
    reason: str,
    details: str | None = None,
) -> ContentReport:
    """File a report against a check-in or a user profile. Idempotent:
    reporting the same target twice returns the original report rather
    than creating a second (the `UNIQUE (reporter_id, target_type,
    target_id)` constraint's own purpose).

    Raises `CheckinNotFoundError` if `target_type` is `checkin` and
    `reporter` can't see it (deleted, or never visible to them).
    """
    existing = await session.execute(
        select(ContentReport).where(
            ContentReport.reporter_id == reporter.id,
            ContentReport.target_type == target_type,
            ContentReport.target_id == target_id,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    if target_type == "checkin":
        await checkin_service.get_checkin(session, target_id, viewer=reporter)

    report = ContentReport(
        reporter_id=reporter.id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        details=details,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def list_content_reports(
    session: AsyncSession, *, status: str | None, limit: int, offset: int
) -> list[ContentReport]:
    """The admin queue, newest first. `status=None` returns every report
    regardless of state; passing `ReportStatus.PENDING` is what an
    actual queue view uses.
    """
    stmt = select(ContentReport).order_by(ContentReport.created_at.desc())
    if status is not None:
        stmt = stmt.where(ContentReport.status == status)
    result = await session.execute(stmt.limit(limit).offset(offset))
    return list(result.scalars().all())


async def _resolve_content_report(
    session: AsyncSession, report_id: uuid.UUID, *, admin_id: uuid.UUID, status: str
) -> ContentReport:
    report = await session.get(ContentReport, report_id)
    if report is None:
        raise ContentReportNotFoundError(f"content report not found: {report_id}")
    report.status = status
    report.resolved_by = admin_id
    report.resolved_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(report)
    return report


async def dismiss_content_report(
    session: AsyncSession, report_id: uuid.UUID, *, admin_id: uuid.UUID
) -> ContentReport:
    """Mark a report reviewed with no action taken."""
    return await _resolve_content_report(
        session, report_id, admin_id=admin_id, status=ReportStatus.DISMISSED
    )


async def action_content_report(
    session: AsyncSession, report_id: uuid.UUID, *, admin_id: uuid.UUID
) -> ContentReport:
    """Mark a report reviewed with action taken elsewhere, removing the
    content or suspending the account. This call only records that the
    review happened, not what the action was; see
    `app.services.checkin.hard_delete_checkin` and
    `app.services.user.suspend_account`.
    """
    return await _resolve_content_report(
        session, report_id, admin_id=admin_id, status=ReportStatus.ACTIONED
    )
