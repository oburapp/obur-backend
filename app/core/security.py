"""Clerk session token verification.

The only module in the app that imports `clerk_backend_api` directly.
Everything else depends on `app.core.auth.get_current_user`, which returns
our own `User` model — never a Clerk type. Swapping or adding an auth
provider later means rewriting this one file.
"""

from clerk_backend_api.security import (
    AuthenticateRequestOptions,
    authenticate_request_async,
)
from fastapi import Request

from app.core.config import get_settings
from app.exceptions import InvalidTokenError

settings = get_settings()


async def verify_session(request: Request) -> str:
    """Verify the incoming request's Clerk session token.

    Returns the authenticated user's ID from the token's `sub` claim.
    Raises `InvalidTokenError` if the request isn't validly signed in.
    """
    # authorized_parties (the `azp` claim check) is intentionally unset —
    # there's no real web/mobile client origin to allowlist yet. Set this
    # once obur-web/obur-mobile exist and their real origins are known.
    options = AuthenticateRequestOptions(secret_key=settings.clerk_secret_key)
    request_state = await authenticate_request_async(request, options)

    if not request_state.is_signed_in or request_state.payload is None:
        raise InvalidTokenError(request_state.message or "request is not signed in")

    user_id = request_state.payload.get("sub")
    if not user_id:
        raise InvalidTokenError("token payload is missing the 'sub' claim")

    return user_id
