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
from app.exceptions import InvalidTokenError
from app.models.user import User

_AUTH_PROVIDER = "clerk"


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated request to a `User` row.

    Verifies the Clerk session token, then looks up the corresponding
    `User` by (auth_provider, auth_provider_id). The Clerk webhook (see
    `app/api/v1/webhooks.py`) is the primary way `User` rows get created
    and kept in sync — this only creates a minimal fallback row for the
    rare race where a first request arrives before that webhook does.
    """
    try:
        auth_provider_id = await verify_session(request)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        ) from e

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
    user = User(auth_provider=_AUTH_PROVIDER, auth_provider_id=auth_provider_id)
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
