"""Admin-only endpoints — a deliberately separate, privileged namespace
rather than a query flag on the regular resource routes, so a
destructive action can't be triggered by accident (see ADR references
in docs/roadmap.md Phase 3).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import require_admin
from app.core.database import get_session
from app.exceptions import CheckinNotFoundError
from app.models.user import User
from app.services import checkin as checkin_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.delete("/checkins/{checkin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def purge_checkin(
    checkin_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Permanently delete a check-in and its product ratings.

    Unlike `DELETE /api/v1/checkins/{id}` (always a soft-delete), this
    actually removes the row — for moderation/takedown cases, not a
    user's routine "remove my own check-in."
    """
    try:
        await checkin_service.hard_delete_checkin(session, checkin_id)
    except CheckinNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Checkin not found"
        ) from e
