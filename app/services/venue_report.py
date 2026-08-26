"""VenueReport domain: data-quality reports against a venue's details
(see ADR-0010 in obur-docs, PDD §11). The only way a venue's details
ever change after creation (ADR-0009).

Unlike `ContentReport`'s user-target case, checking the target exists
is safe and cheap here: `venue_id` is a real foreign key, `venues_select`
has no blocking guard (a venue isn't a person), and every venue stays
visible regardless of `is_active`/`is_suspended`, only their own
"closed"/"suspended" display state changes.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.report_status import ReportStatus
from app.exceptions import VenueReportNotFoundError
from app.models.venue_report import VenueReport
from app.services import venue as venue_service


async def create_venue_report(
    session: AsyncSession,
    *,
    reporter_id: uuid.UUID,
    venue_id: uuid.UUID,
    reason: str,
    details: str | None = None,
) -> VenueReport:
    """File a data-quality report against a venue. Idempotent: reporting
    the same venue twice returns the original report rather than
    creating a second (the `UNIQUE (reporter_id, venue_id)` constraint's
    own purpose).

    Raises `VenueNotFoundError` if `venue_id` doesn't exist.
    """
    existing = await session.execute(
        select(VenueReport).where(
            VenueReport.reporter_id == reporter_id, VenueReport.venue_id == venue_id
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found

    await venue_service.get_venue(session, venue_id)

    report = VenueReport(
        reporter_id=reporter_id, venue_id=venue_id, reason=reason, details=details
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def list_venue_reports(
    session: AsyncSession, *, status: str | None, limit: int, offset: int
) -> list[VenueReport]:
    """The admin queue, newest first. `status=None` returns every report
    regardless of state.
    """
    stmt = select(VenueReport).order_by(VenueReport.created_at.desc())
    if status is not None:
        stmt = stmt.where(VenueReport.status == status)
    result = await session.execute(stmt.limit(limit).offset(offset))
    return list(result.scalars().all())


async def _resolve_venue_report(
    session: AsyncSession, report_id: uuid.UUID, *, admin_id: uuid.UUID, status: str
) -> VenueReport:
    report = await session.get(VenueReport, report_id)
    if report is None:
        raise VenueReportNotFoundError(f"venue report not found: {report_id}")
    report.status = status
    report.resolved_by = admin_id
    report.resolved_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(report)
    return report


async def dismiss_venue_report(
    session: AsyncSession, report_id: uuid.UUID, *, admin_id: uuid.UUID
) -> VenueReport:
    """Mark a report reviewed with no action taken."""
    return await _resolve_venue_report(
        session, report_id, admin_id=admin_id, status=ReportStatus.DISMISSED
    )


async def action_venue_report(
    session: AsyncSession, report_id: uuid.UUID, *, admin_id: uuid.UUID
) -> VenueReport:
    """Mark a report reviewed with action taken elsewhere, correcting the
    venue or setting `is_active`/`is_suspended`. This call only records
    that the review happened, not what the action was; see
    `app.services.venue.close_venue`/`suspend_venue`.
    """
    return await _resolve_venue_report(
        session, report_id, admin_id=admin_id, status=ReportStatus.ACTIONED
    )
