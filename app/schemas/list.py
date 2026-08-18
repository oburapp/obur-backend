"""Schemas for list and list-item resources."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.visibility import Visibility, VisibilityValue

_MAX_TITLE_LENGTH = 200
_MAX_DESCRIPTION_LENGTH = 2000


class ListCreateRequest(BaseModel):
    """Payload to create a list. `user_id` is never accepted from the
    client — it's always the authenticated user.
    """

    title: str = Field(min_length=1, max_length=_MAX_TITLE_LENGTH)
    description: str | None = Field(default=None, max_length=_MAX_DESCRIPTION_LENGTH)
    visibility: VisibilityValue = Visibility.PUBLIC


class ListUpdateRequest(BaseModel):
    """Payload to update a list's editable fields. Every field is
    optional — only fields actually present in the request are changed.
    """

    title: str | None = Field(default=None, min_length=1, max_length=_MAX_TITLE_LENGTH)
    description: str | None = Field(default=None, max_length=_MAX_DESCRIPTION_LENGTH)
    visibility: VisibilityValue | None = None


class ListResponse(BaseModel):
    """Public shape of a List."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    description: str | None
    visibility: str
    created_at: datetime


class ListItemCreateRequest(BaseModel):
    """Payload to add a venue to a list. Omit `after_item_id` to append
    to the end (the common case); pass an existing item's id to insert
    right after it instead.
    """

    venue_id: UUID
    after_item_id: UUID | None = None


class ListItemMoveRequest(BaseModel):
    """Payload to move an existing list item. `after_item_id=None`
    means "move to the very start" — a different default meaning than
    in `ListItemCreateRequest`, since there's no "omit to append" case
    for an item that's already on the list.
    """

    after_item_id: UUID | None = None


class ListItemResponse(BaseModel):
    """Public shape of a ListItem."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    list_id: UUID
    venue_id: UUID
    position: str
    created_at: datetime
