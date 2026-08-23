"""Migrations must not import from `app/`.

A migration is a frozen record of a transition that already happened;
`app/` is what the system looks like now and changes with every refactor.
Coupling the two means an old migration silently depends on code that has
since moved on — Django's own documentation describes the failure exactly:
migrations that import live models "may work initially but will fail in the
future when you try to rerun old migrations (commonly, when you set up a new
installation and run through all the migrations to set up the database)".

This project hit precisely that: a seed migration imported
`app.seeds.global_product_types`, and removing that module (ADR-0011) took
the entire Alembic environment down with it — including the fixture that
migrates the test database.

A rule alone wouldn't have caught it, because the import worked on the day it
was written and only broke months later. This test catches the coupling at
the moment someone introduces it. See ADR-0012 in obur-docs.
"""

import re
from pathlib import Path

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

# Matches `import app...` / `from app... import ...` at the start of a line,
# including indented imports inside a function body.
_APP_IMPORT = re.compile(r"^\s*(?:from|import)\s+app(?:\.|\s|$)", re.MULTILINE)


def test_migrations_directory_is_present() -> None:
    """Guard the guard: a wrong path would make the check below vacuous."""
    assert _VERSIONS_DIR.is_dir()
    assert list(_VERSIONS_DIR.glob("*.py")), "no migration files found to check"


def test_no_migration_imports_application_code() -> None:
    """No file under migrations/versions/ may import from `app/`.

    `migrations/env.py` is deliberately exempt and not scanned here: it is
    Alembic's own configuration, not a migration, and autogenerate needs
    live `Base.metadata` to diff against.
    """
    offenders = {
        path.name: sorted(set(_APP_IMPORT.findall(path.read_text(encoding="utf-8"))))
        for path in sorted(_VERSIONS_DIR.glob("*.py"))
        if _APP_IMPORT.search(path.read_text(encoding="utf-8"))
    }

    assert not offenders, (
        "migrations must be self-contained — carry literal values and "
        f"sa.table() definitions instead of importing from app/: {offenders}"
    )
