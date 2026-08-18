"""Schemas for venue save resources."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.visibility import Visibility, VisibilityValue
from app.models.venue_save import VenueSaveTypeValue


class VenueSaveCreateRequest(BaseModel):
    """Payload to save a venue as visited/wishlist/favorite. `user_id`
    is never accepted from the client — it's always the authenticated
    user.
    """

    venue_id: UUID
    type: VenueSaveTypeValue
    visibility: VisibilityValue = Visibility.PRIVATE


class VenueSaveUpdateRequest(BaseModel):
    """Payload to update a venue save's visibility. `type` and
    `venue_id` aren't editable — delete and re-save instead.
    """

    visibility: VisibilityValue | None = None


class VenueSaveResponse(BaseModel):
    """Public shape of a VenueSave."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    venue_id: UUID
    type: str
    visibility: str
    created_at: datetime
