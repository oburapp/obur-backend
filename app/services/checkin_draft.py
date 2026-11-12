"""Check-in draft domain: create, autosave, list, delete, and the
deletion that happens when a draft is submitted (ADR-0018 in obur-docs).

Expiry is enforced at read time: every query filters out drafts whose
last edit is older than `DRAFT_LIFETIME`, so an expired draft is gone to
its owner at exactly that moment with no scheduled job involved. Expired
rows are physically deleted lazily, whenever their owner lists their
drafts.

Every query is scoped to the caller's own `user_id` as well as relying on
the owner-only RLS policy, so a draft id belonging to someone else behaves
exactly like one that doesn't exist.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CheckinDraftNotFoundError, VenueNotFoundError
from app.models.checkin_draft import CheckinDraft
from app.models.venue import Venue

DRAFT_LIFETIME = timedelta(days=7)


def _is_unexpired() -> ColumnElement[bool]:
    return CheckinDraft.updated_at > func.now() - DRAFT_LIFETIME


async def _ensure_venue_exists(
    session: AsyncSession, venue_id: uuid.UUID | None
) -> None:
    if venue_id is not None and await session.get(Venue, venue_id) is None:
        raise VenueNotFoundError(f"venue not found: {venue_id}")


async def create_draft(
    session: AsyncSession, *, user_id: uuid.UUID, fields: dict[str, Any]
) -> CheckinDraft:
    """Start a draft from whatever the client has so far.

    Raises `VenueNotFoundError` if `fields` names a venue that doesn't
    exist.
    """
    await _ensure_venue_exists(session, fields.get("venue_id"))

    draft = CheckinDraft(user_id=user_id, **fields)
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    return draft


async def get_draft(
    session: AsyncSession, *, user_id: uuid.UUID, draft_id: uuid.UUID
) -> CheckinDraft:
    """Return one of `user_id`'s unexpired drafts.

    Raises `CheckinDraftNotFoundError` if it doesn't exist, has expired,
    or belongs to someone else.
    """
    result = await session.execute(
        select(CheckinDraft).where(
            CheckinDraft.id == draft_id,
            CheckinDraft.user_id == user_id,
            _is_unexpired(),
        )
    )
    draft = result.scalar_one_or_none()
    if draft is None:
        raise CheckinDraftNotFoundError(f"draft not found: {draft_id}")
    return draft


async def list_drafts(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> list[CheckinDraft]:
    """List `user_id`'s unexpired drafts, most recently edited first.
    Physically deletes their expired ones first.
    """
    await session.execute(
        delete(CheckinDraft).where(CheckinDraft.user_id == user_id, ~_is_unexpired())
    )
    await session.commit()

    result = await session.execute(
        select(CheckinDraft)
        .where(CheckinDraft.user_id == user_id, _is_unexpired())
        .order_by(CheckinDraft.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def update_draft(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    draft_id: uuid.UUID,
    updates: dict[str, Any],
) -> CheckinDraft:
    """Apply an autosave. Last write wins: no version check (ADR-0018).
    Always moves `updated_at` forward, even for an empty update, so a
    draft someone is still touching never expires under them.

    Raises `CheckinDraftNotFoundError` as `get_draft` does, and
    `VenueNotFoundError` for an unknown `venue_id`.
    """
    draft = await get_draft(session, user_id=user_id, draft_id=draft_id)
    if "venue_id" in updates:
        await _ensure_venue_exists(session, updates["venue_id"])

    for field, value in updates.items():
        setattr(draft, field, value)
    draft.updated_at = func.now()  # type: ignore[assignment]
    await session.commit()
    await session.refresh(draft)
    return draft


async def delete_draft(
    session: AsyncSession, *, user_id: uuid.UUID, draft_id: uuid.UUID
) -> None:
    """Discard a draft.

    Raises `CheckinDraftNotFoundError` as `get_draft` does.
    """
    draft = await get_draft(session, user_id=user_id, draft_id=draft_id)
    await session.delete(draft)
    await session.commit()


async def discard_submitted_draft(
    session: AsyncSession, *, user_id: uuid.UUID, draft_id: uuid.UUID
) -> None:
    """Delete the draft a check-in was just submitted from, inside the
    caller's transaction (no commit here), so the check-in and the
    deletion succeed or fail together.

    A draft that is already gone (expired, submitted from another device,
    deleted) is not an error: by submission time the client holds the
    complete data and the draft has done its job.
    """
    await session.execute(
        delete(CheckinDraft).where(
            CheckinDraft.id == draft_id, CheckinDraft.user_id == user_id
        )
    )
