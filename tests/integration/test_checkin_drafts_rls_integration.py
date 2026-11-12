"""RLS policy tests for `checkin_drafts` (migration aecd8f51cd44,
ADR-0016 and ADR-0018 in obur-docs), held to ADR-0016's five criteria:

1. Every test runs as the real application role: `db_session` connects
   through `app.core.database.engine`, which uses `app_database_url`.
2. "Can see" and "cannot see" are asserted together.
3. Assertions use raw `select()` / Core statements, never a service, so a
   pass proves the policy rather than the code in front of it.
4. A parity test runs the kind of query this project has shipped bugs
   with before, one that forgets its owner filter, and shows RLS still
   holds.
5. A fail-closed test shows a session with no identity sees nothing.

Unlike every other owned table, there is no admin exception here: an
admin is asserted to see nothing too.
"""

from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, delete, select, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import clear_current_user_identity, set_current_user_identity
from app.models.checkin_draft import CheckinDraft
from app.models.user import User, UserRole
from app.services import checkin_draft as draft_service

_drafts = cast(Table, CheckinDraft.__table__)


async def _create_user(session: AsyncSession, *, role: str = UserRole.USER) -> User:
    user = User(
        auth_provider="clerk",
        auth_provider_id=f"user_{uuid4()}",
        username=f"u{uuid4().hex[:12]}",
        display_name="Test User",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _owned_draft(session: AsyncSession, owner: User) -> UUID:
    await set_current_user_identity(session, owner.id)
    draft = await draft_service.create_draft(
        session, user_id=owner.id, fields={"note": "not shared yet"}
    )
    return draft.id


async def _visible_draft_ids(session: AsyncSession) -> set[UUID]:
    """Every draft id the current identity can see, deliberately with no
    owner filter of its own.
    """
    return set((await session.execute(select(_drafts.c.id))).scalars().all())


async def test_only_the_owner_sees_a_draft_not_a_stranger_or_an_admin(
    db_session: AsyncSession,
) -> None:
    """Criteria 2 and 3, plus the deliberate absence of an admin bypass."""
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    admin = await _create_user(db_session, role=UserRole.ADMIN)
    draft_id = await _owned_draft(db_session, owner)

    await set_current_user_identity(db_session, owner.id)
    assert draft_id in await _visible_draft_ids(db_session)
    await set_current_user_identity(db_session, stranger.id)
    assert draft_id not in await _visible_draft_ids(db_session)
    await set_current_user_identity(db_session, admin.id)
    assert draft_id not in await _visible_draft_ids(db_session)


async def test_a_query_that_forgets_its_owner_filter_still_sees_only_own_drafts(
    db_session: AsyncSession,
) -> None:
    """Criterion 4: two users' drafts exist; an unfiltered query returns
    exactly the caller's.
    """
    alice = await _create_user(db_session)
    bob = await _create_user(db_session)
    alice_draft = await _owned_draft(db_session, alice)
    bob_draft = await _owned_draft(db_session, bob)

    await set_current_user_identity(db_session, alice.id)
    visible = await _visible_draft_ids(db_session)

    assert alice_draft in visible
    assert bob_draft not in visible


async def test_no_identity_set_sees_no_drafts_at_all(
    db_session: AsyncSession,
) -> None:
    """Criterion 5: fail closed. Drafts have no public tier to fall back to."""
    owner = await _create_user(db_session)
    draft_id = await _owned_draft(db_session, owner)

    await clear_current_user_identity(db_session)

    assert draft_id not in await _visible_draft_ids(db_session)


async def test_a_stranger_cannot_update_or_delete_someone_elses_draft(
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session)
    stranger = await _create_user(db_session)
    draft_id = await _owned_draft(db_session, owner)

    await set_current_user_identity(db_session, stranger.id)
    updated = await db_session.execute(
        update(_drafts).where(_drafts.c.id == draft_id).values(note="hijacked")
    )
    deleted = await db_session.execute(delete(_drafts).where(_drafts.c.id == draft_id))

    assert updated.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]
    assert deleted.rowcount == 0  # pyright: ignore[reportAttributeAccessIssue]
    await set_current_user_identity(db_session, owner.id)
    note = await db_session.scalar(
        select(_drafts.c.note).where(_drafts.c.id == draft_id)
    )
    assert note == "not shared yet"


async def test_a_draft_cannot_be_inserted_under_someone_elses_id(
    db_session: AsyncSession,
) -> None:
    victim = await _create_user(db_session)
    forger = await _create_user(db_session)

    await set_current_user_identity(db_session, forger.id)
    with pytest.raises(ProgrammingError, match="row-level security"):
        await db_session.execute(_drafts.insert().values(user_id=victim.id))


async def test_a_draft_cannot_be_handed_over_to_another_user(
    db_session: AsyncSession,
) -> None:
    """The update policy's WITH CHECK: the owner can edit a draft but not
    move it into someone else's account.
    """
    owner = await _create_user(db_session)
    other = await _create_user(db_session)
    draft_id = await _owned_draft(db_session, owner)

    await set_current_user_identity(db_session, owner.id)
    with pytest.raises(ProgrammingError, match="row-level security"):
        await db_session.execute(
            update(_drafts).where(_drafts.c.id == draft_id).values(user_id=other.id)
        )


async def test_deleting_the_account_cascades_its_drafts_away(
    db_session: AsyncSession,
) -> None:
    """Referential cascades bypass RLS, so account deletion still removes
    drafts even though no policy grants anyone else access to them.
    """
    owner = await _create_user(db_session)
    draft_id = await _owned_draft(db_session, owner)

    await set_current_user_identity(db_session, owner.id)
    await db_session.execute(
        User.__table__.delete().where(  # pyright: ignore[reportAttributeAccessIssue]
            User.id == owner.id
        )
    )

    assert draft_id not in await _visible_draft_ids(db_session)
