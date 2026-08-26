"""Report-submission endpoints (ADR-0010 in obur-docs, PDD §11).

Three routers, not one: each report nests under the resource being
reported (`/checkins/{id}/report`, `/users/{id}/report`,
`/venues/{id}/report`), matching how likes and bookmarks already nest
under their own target rather than living under a shared `/reports`
path.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.content_report import ContentReportTargetType
from app.models.user import User
from app.schemas.report import ContentReportCreateRequest, VenueReportCreateRequest
from app.services import content_report as content_report_service
from app.services import venue_report as venue_report_service

checkin_reports_router = APIRouter(prefix="/checkins", tags=["reports"])
user_reports_router = APIRouter(prefix="/users", tags=["reports"])
venue_reports_router = APIRouter(prefix="/venues", tags=["reports"])


@checkin_reports_router.post(
    "/{checkin_id}/report", status_code=status.HTTP_204_NO_CONTENT
)
async def report_checkin(
    checkin_id: UUID,
    payload: ContentReportCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Report a check-in's note or photo. Idempotent."""
    await content_report_service.create_content_report(
        session,
        reporter=current_user,
        target_type=ContentReportTargetType.CHECKIN,
        target_id=checkin_id,
        reason=payload.reason,
        details=payload.details,
    )


@user_reports_router.post("/{user_id}/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_user(
    user_id: UUID,
    payload: ContentReportCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Report a user profile. Idempotent. Works even against someone
    who has since blocked the reporter (see
    app.services.content_report's module docstring).
    """
    await content_report_service.create_content_report(
        session,
        reporter=current_user,
        target_type=ContentReportTargetType.USER,
        target_id=user_id,
        reason=payload.reason,
        details=payload.details,
    )


@venue_reports_router.post("/{venue_id}/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_venue(
    venue_id: UUID,
    payload: VenueReportCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Report a venue's details as wrong, closed, or a duplicate.
    Idempotent.
    """
    await venue_report_service.create_venue_report(
        session,
        reporter_id=current_user.id,
        venue_id=venue_id,
        reason=payload.reason,
        details=payload.details,
    )
