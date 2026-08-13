"""Shared locale constants.

`DEFAULT_LOCALE` is the fallback used whenever a translation is missing
for a user's requested locale — see the PDD's "Translation tables over
embedded strings" design decision. `SUPPORTED_LOCALES` lists every locale
seed data and translation lookups are expected to cover; adding a
language means adding it here and adding the matching module under
app/seeds/locales/.
"""

DEFAULT_LOCALE = "tr"
SUPPORTED_LOCALES: tuple[str, ...] = (DEFAULT_LOCALE,)
