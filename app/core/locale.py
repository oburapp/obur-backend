"""Request-scoped locale resolution.

Separate from app/core/i18n.py, which holds the static locale facts and is
a leaf module `app.models.user` depends on for its column default. This
one needs the authenticated user, so it sits above the models rather than
below them.
"""

from fastapi import Depends, Request

from app.core.auth import get_optional_current_user
from app.core.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, parse_accept_language
from app.models.user import User


async def resolve_locale(
    request: Request,
    viewer: User | None = Depends(get_optional_current_user),
) -> str:
    """Resolve the locale to render this request's catalog labels in.

    A signed-in user's own `locale` wins: it is an explicit choice they
    made in settings (PDD §5), and it should follow them onto a borrowed
    device whose browser is set to something else. `Accept-Language` is
    the fallback for anonymous callers, and `DEFAULT_LOCALE` when neither
    names a locale this application supports.
    """
    if viewer is not None and viewer.locale in SUPPORTED_LOCALES:
        return viewer.locale

    preferred = parse_accept_language(request.headers.get("accept-language"))
    return preferred[0] if preferred else DEFAULT_LOCALE
