"""Canonical VENUE_CATEGORY seed data — language-independent.

Display names live per-locale under app/seeds/locales/, keyed by `slug`.
Adding a category means adding it here, then adding its name to every
module under app/seeds/locales/, then re-running the seeder (`just seed`).
Editing this file alone changes nothing in any database.

The tree classifies **venue format** and nothing else — not cuisine, not
diet. See ADR-0013 in obur-docs for why, including the test an entry has
to pass ("does this name a distinct kind of outing?") and why a handful of
cuisines that have become venue formats in their own right are exceptions.

Two layers, deliberately. Roots are universal and untouched when a new
market is added; leaves are that market's own seed. Every venue is
assigned to a leaf, so where the generic form of a root is itself a real
venue type it appears as a leaf under its own root (`cafe-general`,
`bar-general`). "Restoran" and "Tatlı" get no such leaf: their generic
forms are `lokanta` and `pastane`.

Slugs are stable identifiers, not display text: ASCII, lowercase,
hyphenated, and never changed once seeded. Where a Turkish format has no
English equivalent the slug stays Turkish and the translation glosses it.

Order matters: a category must appear after its parent. The seeder writes
them in one statement and the self-referential foreign key is checked per
statement.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VenueCategorySeed:
    slug: str
    parent_slug: str | None = None


VENUE_CATEGORIES: tuple[VenueCategorySeed, ...] = (
    # --- roots: universal, shared by every market ---
    VenueCategorySeed(slug="restaurant"),
    VenueCategorySeed(slug="cafe"),
    VenueCategorySeed(slug="bar"),
    VenueCategorySeed(slug="dessert"),
    # --- restaurant: Turkish formats ---
    VenueCategorySeed(slug="kebap", parent_slug="restaurant"),
    VenueCategorySeed(slug="doner", parent_slug="restaurant"),
    VenueCategorySeed(slug="pide", parent_slug="restaurant"),
    VenueCategorySeed(slug="lahmacun", parent_slug="restaurant"),
    VenueCategorySeed(slug="kofte", parent_slug="restaurant"),
    VenueCategorySeed(slug="ciger", parent_slug="restaurant"),
    VenueCategorySeed(slug="balik", parent_slug="restaurant"),
    VenueCategorySeed(slug="lokanta", parent_slug="restaurant"),
    VenueCategorySeed(slug="esnaf-lokantasi", parent_slug="restaurant"),
    VenueCategorySeed(slug="kahvalti", parent_slug="restaurant"),
    VenueCategorySeed(slug="brunch", parent_slug="restaurant"),
    VenueCategorySeed(slug="manti", parent_slug="restaurant"),
    VenueCategorySeed(slug="corba", parent_slug="restaurant"),
    VenueCategorySeed(slug="tantuni", parent_slug="restaurant"),
    VenueCategorySeed(slug="kokorec", parent_slug="restaurant"),
    VenueCategorySeed(slug="midye", parent_slug="restaurant"),
    VenueCategorySeed(slug="cig-kofte", parent_slug="restaurant"),
    VenueCategorySeed(slug="bufe", parent_slug="restaurant"),
    VenueCategorySeed(slug="borek", parent_slug="restaurant"),
    # --- restaurant: formats defined by the kind of outing, not the food ---
    VenueCategorySeed(slug="steakhouse", parent_slug="restaurant"),
    VenueCategorySeed(slug="fine-dining", parent_slug="restaurant"),
    VenueCategorySeed(slug="burger", parent_slug="restaurant"),
    VenueCategorySeed(slug="pizza", parent_slug="restaurant"),
    VenueCategorySeed(slug="sandwich", parent_slug="restaurant"),
    # --- restaurant: cuisines that became venue formats here (ADR-0013) ---
    VenueCategorySeed(slug="chinese", parent_slug="restaurant"),
    VenueCategorySeed(slug="sushi", parent_slug="restaurant"),
    VenueCategorySeed(slug="italian", parent_slug="restaurant"),
    VenueCategorySeed(slug="far-east", parent_slug="restaurant"),
    # --- cafe ---
    VenueCategorySeed(slug="cafe-general", parent_slug="cafe"),
    VenueCategorySeed(slug="specialty-coffee", parent_slug="cafe"),
    VenueCategorySeed(slug="kiraathane", parent_slug="cafe"),
    VenueCategorySeed(slug="cay-bahcesi", parent_slug="cafe"),
    # --- bar ---
    VenueCategorySeed(slug="bar-general", parent_slug="bar"),
    VenueCategorySeed(slug="meyhane", parent_slug="bar"),
    VenueCategorySeed(slug="pub", parent_slug="bar"),
    VenueCategorySeed(slug="birahane", parent_slug="bar"),
    VenueCategorySeed(slug="cocktail-bar", parent_slug="bar"),
    VenueCategorySeed(slug="wine-bar", parent_slug="bar"),
    # --- dessert ---
    VenueCategorySeed(slug="pastane", parent_slug="dessert"),
    VenueCategorySeed(slug="baklavaci", parent_slug="dessert"),
    VenueCategorySeed(slug="muhallebici", parent_slug="dessert"),
    VenueCategorySeed(slug="dondurma", parent_slug="dessert"),
    VenueCategorySeed(slug="waffle", parent_slug="dessert"),
    VenueCategorySeed(slug="cikolata", parent_slug="dessert"),
)
