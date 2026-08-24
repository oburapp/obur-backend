"""Integration tests for the RLS per-transaction identity mechanism itself
(ADR-0016 in obur-docs), not for any table's policy: none exist yet.

These prove `app.core.database.set_current_user_identity` and its
`after_begin` counterpart actually reach Postgres correctly: the id is
visible via `current_setting('app.current_user_id', true)` immediately,
it survives across a mid-transaction commit (the scenario the roadmap's
own text calls out (a service's `session.commit()` mid-request), and a
session where identity was never set reads back as no setting at all
(the fail-closed default RLS policies will depend on).
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_current_user_identity


async def _current_setting(session: AsyncSession) -> str | None:
    result = await session.execute(
        text("SELECT current_setting('app.current_user_id', true)")
    )
    value = result.scalar_one()
    return value or None


async def test_set_current_user_identity_applies_to_the_open_transaction(
    db_session: AsyncSession,
) -> None:
    user_id = uuid.uuid4()

    await set_current_user_identity(db_session, user_id)

    assert await _current_setting(db_session) == str(user_id)


async def test_identity_survives_a_mid_transaction_commit(
    db_session: AsyncSession,
) -> None:
    """The exact scenario ADR-0016 is built around: a service's own
    `session.commit()` mid-request ends the transaction the `SET LOCAL`
    was scoped to, so the `after_begin` listener has to re-apply the same
    identity to the new transaction that follows, without anyone calling
    `set_current_user_identity` a second time.
    """
    user_id = uuid.uuid4()
    await set_current_user_identity(db_session, user_id)

    await db_session.commit()

    assert await _current_setting(db_session) == str(user_id)


async def test_no_identity_set_reads_back_as_no_setting(
    db_session: AsyncSession,
) -> None:
    """The fail-closed default: a session that never calls
    `set_current_user_identity` (an anonymous request, or a test fixture
    writing rows directly) must not appear to be any particular user,
    RLS policies read this as "no caller", not as an error.
    """
    assert await _current_setting(db_session) is None
