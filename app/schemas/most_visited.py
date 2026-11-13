"""Response shape for a profile's most-visited places (ADR-0020 in
obur-docs).
"""

import uuid

from pydantic import BaseModel, ConfigDict


class MostVisitedVenue(BaseModel):
    """One venue in the list and how many visits the viewer can count."""

    model_config = ConfigDict(from_attributes=True)

    venue_id: uuid.UUID
    name: str
    category_id: uuid.UUID
    visit_count: int
