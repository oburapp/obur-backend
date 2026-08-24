"""Locale constants and request-time locale resolution.

User-facing labels for platform catalogs (`VENUE_CATEGORY`, and `BADGE`
from Phase 14) live in translation tables rather than on the row itself,
so every read of them has to answer one question first: which locale is
this request in? The constants and parsing here produce that answer, so
each new translated catalog inherits one rule instead of inventing its own.

Deliberately a leaf module: it imports nothing from `app`, because
`app.models.user` depends on `DEFAULT_LOCALE` for its column default.
Resolving a *request's* locale needs the authenticated user and therefore
lives in app/core/locale.py instead.

Adding a language means adding it to `SUPPORTED_LOCALES`, adding the
matching module under app/seeds/locales/, and re-running the seeder. No
code elsewhere changes.
"""

import re

DEFAULT_LOCALE = "tr"
SUPPORTED_LOCALES: tuple[str, ...] = (DEFAULT_LOCALE, "en")

# One `Accept-Language` entry: a tag, optionally followed by a q-value.
# Anything malformed is skipped rather than failing the request — a bad
# header is not a reason to refuse to serve a page.
_ACCEPT_LANGUAGE_ENTRY = re.compile(
    r"^\s*(?P<tag>[A-Za-z*][A-Za-z0-9-]*)\s*(?:;\s*q\s*=\s*(?P<q>[0-9.]+))?\s*$"
)
_DEFAULT_QUALITY = 1.0


def _base_language(tag: str) -> str:
    """Reduce a BCP 47 tag to its primary subtag: `tr-TR` becomes `tr`.

    Regional variants share a translation table here — there is no
    Turkish that differs between Turkey and Germany in a venue category
    name, and pretending otherwise would multiply the seed data for no
    gain.
    """
    return tag.split("-", 1)[0].lower()


def parse_accept_language(header: str | None) -> list[str]:
    """Return the supported locales named in an `Accept-Language` header,
    most-preferred first.

    Unsupported and malformed entries are dropped, so the result is
    always something this application can actually serve.
    """
    if not header:
        return []

    ranked: list[tuple[float, int, str]] = []
    for index, entry in enumerate(header.split(",")):
        match = _ACCEPT_LANGUAGE_ENTRY.match(entry)
        if match is None:
            continue
        try:
            quality = float(match["q"]) if match["q"] is not None else _DEFAULT_QUALITY
        except ValueError:
            continue
        language = _base_language(match["tag"])
        if language in SUPPORTED_LOCALES:
            # `index` keeps the header's own order as the tie-break, which
            # is what the spec expects for equal q-values.
            ranked.append((-quality, index, language))

    return [language for _, _, language in sorted(ranked)]
