"""Schemas for product resources."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductCreateRequest(BaseModel):
    """Payload to create a product at a venue."""

    venue_id: UUID
    global_type_id: UUID
    name: str = Field(min_length=1, max_length=255)


class ProductResponse(BaseModel):
    """Public shape of a Product."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    venue_id: UUID
    global_type_id: UUID
    name: str
    is_available: bool
    created_at: datetime
