"""Admin-only endpoints — a deliberately separate, privileged namespace
rather than a query flag on the regular resource routes, so a
destructive action can't be triggered by accident (see ADR references
in docs/roadmap.md Phase 3).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import require_admin
from app.core.database import get_session
from app.models.user import User
from app.schemas.venue import VenueResponse
from app.services import checkin as checkin_service
from app.services import venue as venue_service

router = APIRouter(prefix="/admin", tags=["admin"])


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
