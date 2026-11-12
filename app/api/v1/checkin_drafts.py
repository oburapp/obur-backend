"""Check-in draft endpoints (ADR-0018 in obur-docs).

Served under `/checkin-drafts` rather than `/checkins/drafts`: the latter
would share a path shape with `/checkins/{checkin_id}`, and whether
"drafts" reached the right handler would then depend on router
registration order.

Every route is owner-only. Another user's draft id answers exactly like
one that never existed.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.models.user import User
from app.schemas.checkin_draft import (
    CheckinDraftCreateRequest,
    CheckinDraftResponse,
    CheckinDraftUpdateRequest,
)
from app.services import checkin_draft as draft_service

router = APIRouter(prefix="/checkin-drafts", tags=["checkin-drafts"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: CheckinDraftCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinDraftResponse:
    """Start a draft. Every field is optional; `visibility` defaults to
    public and can be changed at any time.
    """
    draft = await draft_service.create_draft(
        session, user_id=current_user.id, fields=payload.model_dump()
    )
    return CheckinDraftResponse.model_validate(draft)


@router.get("")
async def list_drafts(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[CheckinDraftResponse]:
    """List your unexpired drafts, most recently edited first."""
    drafts = await draft_service.list_drafts(
        session, current_user.id, limit=limit, offset=offset
    )
    return [CheckinDraftResponse.model_validate(draft) for draft in drafts]


@router.get("/{draft_id}")
async def get_draft(
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinDraftResponse:
    """Return one of your unexpired drafts."""
    draft = await draft_service.get_draft(
        session, user_id=current_user.id, draft_id=draft_id
    )
    return CheckinDraftResponse.model_validate(draft)


@router.patch("/{draft_id}")
async def update_draft(
    draft_id: UUID,
    payload: CheckinDraftUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckinDraftResponse:
    """Autosave. Only fields present in the request change, and the last
    write wins across devices.
    """
    draft = await draft_service.update_draft(
        session,
        user_id=current_user.id,
        draft_id=draft_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    return CheckinDraftResponse.model_validate(draft)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Discard a draft."""
    await draft_service.delete_draft(
        session, user_id=current_user.id, draft_id=draft_id
    )
