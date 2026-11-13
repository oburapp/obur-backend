"""Mentions and hashtags on a check-in's create and edit paths
(ADR-0019 in obur-docs). Kept apart from app.services.checkin so that
module stays about the check-in itself.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text_tokens import parse_hashtags
from app.models.checkin import Checkin
from app.services.hashtag import sync_checkin_hashtags
from app.services.mention import MentionPlan, apply_mentions, plan_checkin_edit


async def plan_edit_tagging(
    session: AsyncSession, checkin: Checkin, updates: dict[str, object]
) -> tuple[MentionPlan, list[str] | None] | None:
    """Mentions follow both the note and the visibility (who can see the
    check-in decides who may stay mentioned); hashtags follow the note
    only. None when the edit touches neither.
    """
    if "note" not in updates and "visibility" not in updates:
        return None
    new_note = updates.get("note", checkin.note)
    plan = await plan_checkin_edit(
        session,
        checkin,
        new_note=new_note,  # type: ignore[arg-type]
        visibility=updates.get("visibility", checkin.visibility),  # type: ignore[arg-type]
    )
    tags = parse_hashtags(new_note) if "note" in updates else None  # type: ignore[arg-type]
    return plan, tags


async def write_tagging(
    session: AsyncSession,
    checkin: Checkin,
    *,
    plan: MentionPlan,
    tags: list[str] | None,
) -> None:
    """Write mentions and, when the note changed (`tags` not None),
    hashtags, inside the caller's transaction (ADR-0019).
    """
    await apply_mentions(
        session, checkin_id=checkin.id, author_id=checkin.user_id, plan=plan
    )
    if tags is not None:
        await sync_checkin_hashtags(session, checkin_id=checkin.id, tags=tags)
