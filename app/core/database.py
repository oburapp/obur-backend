"""Async SQLAlchemy engine, session factory, connectivity check, and the
Row Level Security identity mechanism (ADR-0016 in obur-docs).

RLS policies read the caller's id from a per-transaction Postgres setting
(`app.current_user_id`), set with `SET LOCAL` so it can never survive past
the transaction it was set for and leak onto a pooled connection reused by
a later, unrelated request. Two things have to be true for that to work
with this app's actual request lifecycle, where a transaction can already
be open by the time the caller's identity becomes known (`app.core.auth`
resolves it partway through, after the session's first query) and where a
single request can span more than one transaction (a service's own
`session.commit()` mid-request ends the transaction the setting was
scoped to):

1. `set_current_user_identity()` applies the setting immediately, to
   whatever transaction happens to be open right now, the moment the
   caller's identity is known.
2. The `after_begin` listener below re-applies the same identity
   automatically every time the session starts a *new* transaction after
   that (a mid-request commit, for example), by reading it back from
   `session.info`, where (1) also records it for exactly this purpose.
"""

import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(settings.app_database_url, pool_pre_ping=True)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

# `session.info` key `set_current_user_identity` writes to and the
# `after_begin` listener reads back. Not a bare string inline at each use
# site, so a typo in one place can't silently desync the two.
_CURRENT_USER_ID_INFO_KEY = "rls_current_user_id"


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, for use with FastAPI's `Depends`."""
    async with async_session_factory() as session:
        yield session


async def check_database_connection() -> bool:
    """Verify the database is reachable by executing a trivial query."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


async def set_current_user_identity(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Record the authenticated caller's id for RLS, and apply it to the
    transaction that's open right now.

    Called once, from `app.core.auth.get_current_user`, the moment a
    request's caller is known. `session.info` is plain in-memory state on
    the session object, not database state, so recording it here is safe
    to do before any `SET LOCAL` is issued.

    `SET LOCAL` does not accept bind parameters (the same PostgreSQL
    protocol limitation already hit and documented in
    `app/services/venue.py`), so the id is interpolated directly. Safe
    here specifically because a `uuid.UUID`'s `str()` form is always a
    fixed set of hex digits and dashes, never attacker-influenced text,
    unlike arbitrary request input.
    """
    session.info[_CURRENT_USER_ID_INFO_KEY] = user_id
    await session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))


async def clear_current_user_identity(session: AsyncSession) -> None:
    """Reverse of `set_current_user_identity`: forget the recorded caller,
    so this session reverts to looking like an anonymous request to RLS.

    Symmetric counterpart kept for the same reason `set_current_user_identity`
    exists rather than inlining `SET LOCAL` at each call site: without
    clearing `session.info` too, the `after_begin` listener would keep
    re-applying the old identity to every later transaction on this
    session, clearing only the transaction that's open right now
    wouldn't be enough. Not currently called from application code
    (nothing in this app steps back down to anonymous mid-session), but
    real integration test coverage of the fail-closed default
    (ADR-0016) needs a session that provably has no identity, not just
    one that never set one, since that's indistinguishable from a bug
    that silently forgot to.

    `SET LOCAL ... TO DEFAULT`, not bare `RESET`: `RESET` operates at
    session scope, not transaction scope, so on a pooled connection its
    effect can survive past this transaction's rollback and leak into
    whatever the connection is reused for next, found empirically (a
    later, unrelated test started seeing `current_setting` return an
    empty string instead of `NULL`). `SET LOCAL ... TO DEFAULT` keeps
    the same transaction-scoped guarantee `set_current_user_identity`
    already relies on.
    """
    session.info.pop(_CURRENT_USER_ID_INFO_KEY, None)
    await session.execute(text("SET LOCAL app.current_user_id TO DEFAULT"))


def _apply_rls_identity_on_new_transaction(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """`after_begin` fires every time a session starts a new transaction,
    including the autobegin that follows a mid-request `session.commit()`
    exactly the "per-transaction, not per-request" behaviour RLS needs,
    since `SET LOCAL`'s previous value doesn't survive a transaction
    boundary.

    Must call `connection.execute(...)`, not `session.execute(...)`: the
    session is mid-provisioning while this event fires, and calling back
    into it raises `InvalidRequestError` on SQLAlchemy 2.0.17+ (see
    ADR-0016's sources). The `connection` this handler receives is exactly
    the one whose transaction is being entered, so this still reaches the
    right transaction despite going around the session.

    A session with no recorded identity (an anonymous request, or one
    that never called `set_current_user_identity`) is left alone here:
    RLS policies read a missing setting as "no caller", not as an error,
    and still have to allow `public`-visibility rows through for it.
    """
    user_id = session.info.get(_CURRENT_USER_ID_INFO_KEY)
    if user_id is None:
        return
    connection.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))


event.listen(Session, "after_begin", _apply_rls_identity_on_new_transaction)
