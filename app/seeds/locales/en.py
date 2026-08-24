"""English (en) display names for seed data.

Keys must match the slugs in app/seeds/venue_categories.py exactly —
the seeder looks each slug up here and fails fast with a KeyError if one
is missing.

Turkish venue formats with no English equivalent keep their own name and
gain a short gloss ("Meyhane (Turkish Tavern)") rather than being
flattened into a nearby English word. An esnaf lokantası is not a
canteen, and calling it one would make the category useless for the
filtering and ranking that read it. See ADR-0013.
"""

VENUE_CATEGORY_NAMES: dict[str, str] = {
    "restaurant": "Restaurant",
    "cafe": "Cafe",
    "bar": "Bar",
    "dessert": "Dessert",
    "kebap": "Kebab House",
    "doner": "Doner Shop",
    "pide": "Pide House",
    "lahmacun": "Lahmacun",
    "kofte": "Meatball House",
    "ciger": "Liver House",
    "balik": "Seafood Restaurant",
    "lokanta": "Lokanta (Turkish Restaurant)",
    "esnaf-lokantasi": "Esnaf Lokantası (Tradesman's Eatery)",
    "kahvalti": "Turkish Breakfast",
    "brunch": "Brunch",
    "manti": "Mantı House",
    "corba": "Soup House",
    "tantuni": "Tantuni",
    "kokorec": "Kokoreç",
    "midye": "Stuffed Mussels",
    "cig-kofte": "Çiğ Köfte",
    "bufe": "Büfe (Corner Shop Eatery)",
    "borek": "Börek Shop",
    "steakhouse": "Steakhouse",
    "fine-dining": "Fine Dining",
    "burger": "Burger",
    "pizza": "Pizza",
    "sandwich": "Sandwich",
    "chinese": "Chinese",
    "sushi": "Sushi",
    "italian": "Italian",
    "far-east": "Far Eastern",
    "cafe-general": "Cafe",
    "specialty-coffee": "Specialty Coffee",
    "kiraathane": "Kıraathane (Traditional Coffee House)",
    "cay-bahcesi": "Tea Garden",
    "bar-general": "Bar",
    "meyhane": "Meyhane (Turkish Tavern)",
    "pub": "Pub",
    "birahane": "Beer Hall",
    "cocktail-bar": "Cocktail Bar",
    "wine-bar": "Wine Bar",
    "pastane": "Patisserie",
    "baklavaci": "Baklava Shop",
    "muhallebici": "Milk Pudding Shop",
    "dondurma": "Ice Cream",
    "waffle": "Waffle",
    "cikolata": "Chocolate & Cookies",
}
