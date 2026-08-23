"""Per-locale seed translations.

Each locale module in this package (e.g. `tr.py`) exports one dict,
`VENUE_CATEGORY_NAMES`, keyed by the slugs defined in
app/seeds/venue_categories.py.

Adding a language: add a new module here, named after the locale code
(e.g. `en.py`), covering every slug in that dict, and add the code to
`SUPPORTED_LOCALES` in app/core/i18n.py — nothing else has to change.
"""

import importlib

from app.core.i18n import SUPPORTED_LOCALES

_LOCALE_NAME_TABLES = {
    locale: importlib.import_module(f"{__name__}.{locale}")
    for locale in SUPPORTED_LOCALES
}


def get_venue_category_names(locale: str) -> dict[str, str]:
    """Return the slug -> display name table for VENUE_CATEGORY in `locale`."""
    return _LOCALE_NAME_TABLES[locale].VENUE_CATEGORY_NAMES
