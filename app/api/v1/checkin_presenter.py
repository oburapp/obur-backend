"""Turning `Checkin` rows into `CheckinResponse` bodies, mentions
included. Every endpoint that returns a check-in goes through here, so a
listing resolves all of its mentions in one query rather than one per
check-in (ADR-0019 in obur-docs).
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.checkin import Checkin
from app.schemas.checkin import CheckinResponse, MentionResponse
from app.services.mention import mention_views


async def checkin_responses(
    session: AsyncSession, checkins: Sequence[Checkin]
) -> list[CheckinResponse]:
    """Responses for `checkins`, in the same order."""
    views = await mention_views(session, checkins)
    return [
        CheckinResponse.model_validate(checkin).model_copy(
            update={
                "mentions": [
                    MentionResponse.model_validate(view, from_attributes=True)
                    for view in views[checkin.id]
                ]
            }
        )
        for checkin in checkins
    ]


async def checkin_response(session: AsyncSession, checkin: Checkin) -> CheckinResponse:
    """The response for a single check-in."""
    (response,) = await checkin_responses(session, [checkin])
    return response
