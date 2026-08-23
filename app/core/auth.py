"""FastAPI auth dependency: resolves the authenticated request to our User.

Route handlers depend on `get_current_user` only. It's the boundary
between Clerk-specific verification (`app.core.security`) and the rest of
the app, which only ever sees our own `User` model.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import verify_session
from app.core.user_identity import fallback_username
from app.exceptions import InvalidTokenError
from app.models.user import User

_AUTH_PROVIDER = "clerk"


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated request to a `User` row, for endpoints
    that require a signed-in caller.
    """
    try:
        return await _resolve_user(request, session)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        ) from e


async def get_optional_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Same resolution as `get_current_user`, but returns `None` instead
    of raising 401 when there's no (or an invalid) session token.

    For endpoints that are public but behave differently for a known
    viewer — e.g. a check-in listing that includes the viewer's own
    private check-ins alongside everyone's public ones.
    """
    try:
        return await _resolve_user(request, session)
    except InvalidTokenError:
        return None


async def _resolve_user(request: Request, session: AsyncSession) -> User:
    """Verify the Clerk session token, then look up the corresponding
    `User` by (auth_provider, auth_provider_id).

    The Clerk webhook (see `app/api/v1/webhooks.py`) is the primary way
    `User` rows get created and kept in sync — this only creates a
    minimal fallback row for the rare race where a first request arrives
    before that webhook does.

    Raises `InvalidTokenError` if the request isn't validly signed in —
    callers decide how to react (401, or treat as anonymous).
    """
    auth_provider_id = await verify_session(request)

    user = await _find_user(session, auth_provider_id)
    if user is not None:
        return user

    return await _create_user_jit(session, auth_provider_id)


async def _find_user(session: AsyncSession, auth_provider_id: str) -> User | None:
    result = await session.execute(
        select(User).where(
            User.auth_provider == _AUTH_PROVIDER,
            User.auth_provider_id == auth_provider_id,
        )
    )
    return result.scalar_one_or_none()


async def _create_user_jit(session: AsyncSession, auth_provider_id: str) -> User:
    """Create the minimal fallback row for a user the webhook hasn't
    reached yet.

    `username` and `display_name` are required but unknown here — the
    session token carries no profile data — so both are derived from the
    provider identity (see app.core.user_identity), exactly as the
    webhook derives them when Clerk supplies no username. Whichever path
    wins the race therefore writes the same values, and the webhook's
    later `user.updated` deliberately won't overwrite them.
    """
    username = fallback_username(_AUTH_PROVIDER, auth_provider_id)
    user = User(
        auth_provider=_AUTH_PROVIDER,
        auth_provider_id=auth_provider_id,
        username=username,
        display_name=username,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Lost a race with a concurrent request (or the webhook) creating
        # the same user — that row is now the real one, use it.
        await session.rollback()
        existing = await _find_user(session, auth_provider_id)
        if existing is None:
            raise
        return existing
    await session.refresh(user)
    return user
