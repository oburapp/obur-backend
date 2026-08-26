"""Admin-only endpoints — a deliberately separate, privileged namespace
rather than a query flag on the regular resource routes, so a
destructive action can't be triggered by accident (see ADR references
in docs/roadmap.md Phase 3).

Excluded from the public OpenAPI schema (`include_in_schema=False`):
`require_admin` is the real, load-bearing authorization boundary, this
is a hygiene measure on top of it, not instead of it. A web/mobile
client has no legitimate reason to discover these routes by browsing
`/docs`; a future admin panel calls them directly by URL the same way
`obur-web`/`obur-mobile` already call the public ones, no schema entry
required either way.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import require_admin
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.report_status import ReportStatusValue
from app.models.user import User
from app.schemas.report import ContentReportResponse, VenueReportResponse
from app.schemas.user import UserResponse
from app.schemas.venue import VenueResponse
from app.services import checkin as checkin_service
from app.services import content_report as content_report_service
from app.services import user as user_service
from app.services import venue as venue_service
from app.services import venue_report as venue_report_service

router = APIRouter(prefix="/admin", tags=["admin"], include_in_schema=False)


@router.delete("/checkins/{checkin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def purge_checkin(
    checkin_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently delete a check-in.

    Unlike `DELETE /api/v1/checkins/{id}` (always a soft-delete), this
    actually removes the row — for moderation/takedown cases, not a
    user's routine "remove my own check-in."
    """
    await checkin_service.hard_delete_checkin(session, checkin_id)


@router.post("/venues/{venue_id}/verify")
async def verify_venue(
    venue_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> VenueResponse:
    """Confirm a venue that has no `google_places_id`, the admin half of
    ADR-0009's hybrid verification design (a `google_places_id` match
    verifies automatically from enough check-ins alone, see
    `app.services.venue.evaluate_venue_verification`).

    Raises `VenueNotFoundError` if `venue_id` doesn't exist.

    Raises `VenueNotEligibleForVerificationError` if the venue hasn't
    reached the required number of independent check-ins yet.
    """
    venue = await venue_service.verify_venue_by_admin(session, venue_id)
    return VenueResponse.model_validate(venue)


@router.post("/venues/{venue_id}/close")
async def close_venue(
    venue_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> VenueResponse:
    """Mark a venue permanently closed. Stays visible, shown
    transparently (PDD §13). Raises `VenueNotFoundError` if `venue_id`
    doesn't exist.
    """
    venue = await venue_service.close_venue(session, venue_id)
    return VenueResponse.model_validate(venue)


@router.post("/venues/{venue_id}/suspend")
async def suspend_venue(
    venue_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> VenueResponse:
    """Suspend a venue: hidden entirely, RLS included, for listings that
    should never have existed. Never user-reversible. Raises
    `VenueNotFoundError` if `venue_id` doesn't exist.
    """
    venue = await venue_service.suspend_venue(session, venue_id)
    return VenueResponse.model_validate(venue)


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Suspend an account. Never user-reversible (PDD §6, §11). Raises
    `UserNotFoundError` if `user_id` doesn't exist.
    """
    user = await user_service.suspend_account(session, user_id)
    return UserResponse.model_validate(user)


@router.get("/content-reports")
async def list_content_reports(
    report_status: ReportStatusValue | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ContentReportResponse]:
    """The check-in/profile report queue, newest first. `status`
    filters to one state; omitted, every report comes back regardless
    of state.
    """
    reports = await content_report_service.list_content_reports(
        session, status=report_status, limit=limit, offset=offset
    )
    return [ContentReportResponse.model_validate(r) for r in reports]


@router.post("/content-reports/{report_id}/dismiss")
async def dismiss_content_report(
    report_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ContentReportResponse:
    """Mark a content report reviewed with no action taken. Raises
    `ContentReportNotFoundError` if `report_id` doesn't exist.
    """
    report = await content_report_service.dismiss_content_report(
        session, report_id, admin_id=admin.id
    )
    return ContentReportResponse.model_validate(report)


@router.post("/content-reports/{report_id}/action")
async def action_content_report(
    report_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ContentReportResponse:
    """Mark a content report reviewed with action taken elsewhere, via
    `DELETE /admin/checkins/{id}` or `POST /admin/users/{id}/suspend`.
    Raises `ContentReportNotFoundError` if `report_id` doesn't exist.
    """
    report = await content_report_service.action_content_report(
        session, report_id, admin_id=admin.id
    )
    return ContentReportResponse.model_validate(report)


@router.get("/venue-reports")
async def list_venue_reports(
    report_status: ReportStatusValue | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[VenueReportResponse]:
    """The venue data-quality report queue, newest first."""
    reports = await venue_report_service.list_venue_reports(
        session, status=report_status, limit=limit, offset=offset
    )
    return [VenueReportResponse.model_validate(r) for r in reports]


@router.post("/venue-reports/{report_id}/dismiss")
async def dismiss_venue_report(
    report_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> VenueReportResponse:
    """Mark a venue report reviewed with no action taken. Raises
    `VenueReportNotFoundError` if `report_id` doesn't exist.
    """
    report = await venue_report_service.dismiss_venue_report(
        session, report_id, admin_id=admin.id
    )
    return VenueReportResponse.model_validate(report)


@router.post("/venue-reports/{report_id}/action")
async def action_venue_report(
    report_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> VenueReportResponse:
    """Mark a venue report reviewed with action taken elsewhere, via
    `POST /admin/venues/{id}/close` or `.../suspend`. Raises
    `VenueReportNotFoundError` if `report_id` doesn't exist.
    """
    report = await venue_report_service.action_venue_report(
        session, report_id, admin_id=admin.id
    )
    return VenueReportResponse.model_validate(report)
