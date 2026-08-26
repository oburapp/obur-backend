"""Schemas for the reporting domain (ADR-0010 in obur-docs, PDD §11)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.content_report import ContentReportReasonValue
from app.models.venue_report import VenueReportReasonValue

# Matches app.schemas.checkin's _MAX_NOTE_LENGTH / app.schemas.list's
# _MAX_DESCRIPTION_LENGTH: the same free-text ceiling this codebase
# already converged on for a user-authored paragraph, not a fresh
# number for this one field.
_MAX_DETAILS_LENGTH = 2000


class ContentReportCreateRequest(BaseModel):
    """Payload to report a check-in or a user profile. `reporter_id` and
    `target_type`/`target_id` are never accepted from the client, they
    come from the authenticated caller and the route path.
    """

    reason: ContentReportReasonValue
    details: str | None = Field(default=None, max_length=_MAX_DETAILS_LENGTH)

    @model_validator(mode="after")
    def _details_required_for_other(self) -> "ContentReportCreateRequest":
        """Mirrors `ck_content_reports_details_required_for_other`
        (migration 190c719287e2): checked here too so a caller gets a
        clear 422 instead of the raw database constraint violation.
        """
        if self.reason == "other" and not (self.details and self.details.strip()):
            raise ValueError("details is required when reason is 'other'")
        return self


class VenueReportCreateRequest(BaseModel):
    """Payload to report a venue's details. `reporter_id`/`venue_id`
    are never accepted from the client.
    """

    reason: VenueReportReasonValue
    details: str | None = Field(default=None, max_length=_MAX_DETAILS_LENGTH)

    @model_validator(mode="after")
    def _details_required_for_other(self) -> "VenueReportCreateRequest":
        """Mirrors `ck_venue_reports_details_required_for_other`
        (migration 190c719287e2)."""
        if self.reason == "other" and not (self.details and self.details.strip()):
            raise ValueError("details is required when reason is 'other'")
        return self


class ContentReportResponse(BaseModel):
    """Admin-facing shape of a ContentReport."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reporter_id: UUID | None
    target_type: str
    target_id: UUID
    reason: str
    details: str | None
    status: str
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime


class VenueReportResponse(BaseModel):
    """Admin-facing shape of a VenueReport."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reporter_id: UUID | None
    venue_id: UUID
    reason: str
    details: str | None
    status: str
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime
