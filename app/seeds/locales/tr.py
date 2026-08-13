"""Turkish (tr) display names for seed data.

Keys must match the slugs in app/seeds/venue_categories.py and
app/seeds/global_product_types.py exactly — the seed migration looks
each slug up here and fails fast with a KeyError if one is missing.
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

GLOBAL_PRODUCT_TYPE_NAMES: dict[str, str] = {
    "kusbasili-pide": "Kuşbaşılı Pide",
    "kiymali-pide": "Kıymalı Pide",
    "adana-kebap": "Adana Kebap",
    "urfa-kebap": "Urfa Kebap",
    "iskender": "İskender",
    "tavuk-doner": "Tavuk Döner",
    "et-doner": "Et Döner",
    "filter-coffee": "Filtre Kahve",
    "turkish-coffee": "Türk Kahvesi",
    "latte": "Latte",
    "baklava": "Baklava",
    "kunefe": "Künefe",
}
