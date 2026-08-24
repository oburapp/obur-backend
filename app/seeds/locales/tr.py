"""Turkish (tr) display names for seed data.

Keys must match the slugs in app/seeds/venue_categories.py exactly —
the seeder looks each slug up here and fails fast with a KeyError if one
is missing.

Names follow usage rather than a mechanical derivation: the `-ci`/`-cı`
form where that is genuinely the word, the dish alone where the suffix
reads as forced, and a full phrase where the short form is ambiguous
("Balık Lokantası", since a balıkçı also sells fish). See ADR-0013.
"""

VENUE_CATEGORY_NAMES: dict[str, str] = {
    "restaurant": "Restoran",
    "cafe": "Kafe",
    "bar": "Bar",
    "dessert": "Tatlı",
    "kebap": "Kebap Salonu",
    "doner": "Dönerci",
    "pide": "Pideci",
    "lahmacun": "Lahmacun Salonu",
    "kofte": "Köfteci",
    "ciger": "Ciğerci",
    "balik": "Balık Lokantası",
    "lokanta": "Lokanta",
    "esnaf-lokantasi": "Esnaf Lokantası",
    "kahvalti": "Kahvaltı Salonu",
    "brunch": "Brunch",
    "manti": "Mantıcı",
    "corba": "Çorbacı",
    "tantuni": "Tantuni",
    "kokorec": "Kokoreç",
    "midye": "Midyeci",
    "cig-kofte": "Çiğ Köfteci",
    "bufe": "Büfe",
    "borek": "Börekçi",
    "steakhouse": "Steakhouse",
    "fine-dining": "Fine Dining",
    "burger": "Burger",
    "pizza": "Pizza",
    "sandwich": "Sandviç",
    "chinese": "Çin Lokantası",
    "sushi": "Suşi",
    "italian": "İtalyan Lokantası",
    "far-east": "Uzak Doğu",
    "cafe-general": "Kafe",
    "specialty-coffee": "Üçüncü Nesil Kahve",
    "kiraathane": "Kıraathane",
    "cay-bahcesi": "Çay Bahçesi",
    "bar-general": "Bar",
    "meyhane": "Meyhane",
    "pub": "Pub",
    "birahane": "Birahane",
    "cocktail-bar": "Kokteyl Bar",
    "wine-bar": "Şarap Barı",
    "pastane": "Pastane",
    "baklavaci": "Baklavacı",
    "muhallebici": "Muhallebici",
    "dondurma": "Dondurmacı",
    "waffle": "Waffle",
    "cikolata": "Çikolata & Kurabiye",
}
