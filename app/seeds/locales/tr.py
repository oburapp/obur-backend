"""Turkish (tr) display names for seed data.

Keys must match the slugs in app/seeds/venue_categories.py exactly —
the seed migration looks each slug up here and fails fast with a
KeyError if one is missing.
"""

VENUE_CATEGORY_NAMES: dict[str, str] = {
    "food": "Yeme İçme",
    "kebap": "Kebap",
    "pide": "Pide",
    "doner": "Döner",
    "fast-food": "Fast Food",
    "cafe": "Kafe",
    "bar": "Bar",
    "dessert": "Tatlı",
    "bakery": "Fırın",
}
