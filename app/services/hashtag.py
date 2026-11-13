"""Hashtag domain (ADR-0019 in obur-docs): keeping `checkin_hashtags` and
`list_hashtags` in step with the text they're parsed from, and the two
hashtag pages.

Link rows are rewritten from the text on every create and edit, inside
the caller's transaction. Tags are upserted in bulk, so two people
introducing the same new tag at once can't collide.

A hashtag page shows only `public` content from visible accounts, hides
content where either side has blocked the other, and shows muted
accounts' content: muting affects only the muter's own feed (PDD §11).
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import account_is_visible, not_blocked_with
from app.core.text_tokens import hashtag_key
from app.core.visibility import Visibility
from app.models.checkin import Checkin
from app.models.hashtag import CheckinHashtag, Hashtag, ListHashtag
from app.models.list import List
from app.models.user import User


async def _hashtag_ids(session: AsyncSession, tags: list[str]) -> list[uuid.UUID]:
    """Ids for `tags` (as typed), creating any that don't exist yet."""
    keys = sorted({hashtag_key(tag) for tag in tags})
    if not keys:
        return []
    await session.execute(
        insert(Hashtag)
        .values([{"tag": key} for key in keys])
        .on_conflict_do_nothing(index_elements=[Hashtag.tag])
    )
    result = await session.execute(select(Hashtag.id).where(Hashtag.tag.in_(keys)))
    return list(result.scalars().all())


async def sync_checkin_hashtags(
    session: AsyncSession, *, checkin_id: uuid.UUID, tags: list[str]
) -> None:
    """Make `checkin_id`'s hashtag links exactly `tags`. No commit."""
    ids = await _hashtag_ids(session, tags)
    await session.execute(
        delete(CheckinHashtag).where(
            CheckinHashtag.checkin_id == checkin_id,
            CheckinHashtag.hashtag_id.not_in(ids),
        )
    )
    if ids:
        await session.execute(
            insert(CheckinHashtag)
            .values([{"checkin_id": checkin_id, "hashtag_id": hid} for hid in ids])
            .on_conflict_do_nothing()
        )


async def sync_list_hashtags(
    session: AsyncSession, *, list_id: uuid.UUID, tags: list[str]
) -> None:
    """Make `list_id`'s hashtag links exactly `tags`. No commit."""
    ids = await _hashtag_ids(session, tags)
    await session.execute(
        delete(ListHashtag).where(
            ListHashtag.list_id == list_id, ListHashtag.hashtag_id.not_in(ids)
        )
    )
    if ids:
        await session.execute(
            insert(ListHashtag)
            .values([{"list_id": list_id, "hashtag_id": hid} for hid in ids])
            .on_conflict_do_nothing()
        )


def _discoverable(owner_column: Any, viewer: User | None) -> list[ColumnElement[bool]]:
    conditions = [account_is_visible(owner_column)]
    if viewer is not None:
        conditions.append(not_blocked_with(owner_column, viewer.id))
    return conditions


async def list_checkins_for_hashtag(
    session: AsyncSession,
    tag: str,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[Checkin]:
    """Public check-ins carrying `tag` (any casing), newest first."""
    result = await session.execute(
        select(Checkin)
        .join(CheckinHashtag, CheckinHashtag.checkin_id == Checkin.id)
        .join(Hashtag, Hashtag.id == CheckinHashtag.hashtag_id)
        .where(
            Hashtag.tag == hashtag_key(tag),
            Checkin.visibility == Visibility.PUBLIC,
            Checkin.deleted_at.is_(None),
            *_discoverable(Checkin.user_id, viewer),
        )
        .order_by(Checkin.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def list_lists_for_hashtag(
    session: AsyncSession,
    tag: str,
    *,
    viewer: User | None,
    limit: int,
    offset: int,
) -> list[List]:
    """Public lists carrying `tag` (any casing), newest first."""
    result = await session.execute(
        select(List)
        .join(ListHashtag, ListHashtag.list_id == List.id)
        .join(Hashtag, Hashtag.id == ListHashtag.hashtag_id)
        .where(
            Hashtag.tag == hashtag_key(tag),
            List.visibility == Visibility.PUBLIC,
            *_discoverable(List.user_id, viewer),
        )
        .order_by(List.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
