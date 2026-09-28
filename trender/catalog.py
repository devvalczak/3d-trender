"""Startowa lista fraz/produktów do monitorowania z typowymi parametrami produkcji.

Waga i czas to typowe wartości dla Bambu Lab P1S (profil 0.20 mm Standard).
Po znalezieniu konkretnego modelu nadpisz je danymi z Bambu Studio (wgraj .3mf/.gcode).
"""

from __future__ import annotations

# (fraza PL, fraza EN, kategoria, waga g, czas h, filament, obróbka min, zmiany koloru, sezony)
SEED: list[tuple] = [
    ("organizer na biurko", "desk organizer", "Dom i biuro", 150, 5.0, "pla", 3, 0, ["all_year", "back_to_school"]),
    ("gridfinity", "gridfinity bin", "Warsztat", 55, 1.8, "pla", 1, 0, ["all_year"]),
    ("organizer do szuflady", "drawer organizer", "Dom i biuro", 90, 3.0, "pla", 1, 0, ["all_year"]),
    ("uchwyt na kable", "cable organizer", "Dom i biuro", 15, 0.6, "pla", 1, 0, ["all_year"]),
    ("podstawka pod telefon", "phone stand", "Gadżety", 45, 1.5, "pla", 2, 0, ["all_year"]),
    ("stojak na słuchawki", "headphone stand", "Gadżety", 110, 4.0, "pla", 3, 0, ["all_year", "christmas"]),
    ("stojak na pada", "controller stand", "Gaming", 60, 2.5, "pla", 2, 0, ["all_year", "christmas"]),
    ("akcesoria ikea skadis", "ikea skadis accessories", "Warsztat", 30, 1.0, "petg", 1, 0, ["all_year"]),
    ("wieszak na klucze", "key holder", "Dom i biuro", 50, 2.0, "pla", 2, 0, ["all_year"]),
    ("stojak na przyprawy", "spice rack", "Kuchnia", 200, 8.0, "petg", 3, 0, ["all_year", "christmas"]),
    ("foremki do ciastek", "cookie cutter", "Kuchnia", 15, 0.7, "petg", 1, 0, ["christmas", "easter", "halloween"]),
    ("doniczka samonawadniająca", "self watering planter", "Ogród", 120, 5.0, "petg", 2, 0, ["summer", "mothers_day"]),
    ("wazon spiralny", "spiral vase", "Dekoracje", 80, 3.0, "silk", 1, 0, ["all_year", "mothers_day", "womens_day"]),
    ("lampa księżyc", "moon lamp", "Dekoracje", 90, 7.0, "pla", 10, 0, ["christmas", "valentines"]),
    ("litofan ze zdjęciem", "lithophane", "Personalizowane", 40, 3.0, "pla", 10, 0,
     ["mothers_day", "fathers_day", "christmas", "valentines"]),
    ("smok articulated", "articulated dragon", "Zabawki", 60, 5.0, "silk", 3, 0, ["all_year", "childrens_day", "christmas"]),
    ("fidget toy", "fidget toy", "Zabawki", 20, 1.0, "pla", 1, 0, ["all_year", "childrens_day", "back_to_school"]),
    ("breloczek z imieniem", "name keychain", "Personalizowane", 8, 0.4, "pla", 3, 4, ["all_year", "back_to_school"]),
    ("tabliczka z imieniem", "name sign", "Personalizowane", 40, 2.0, "pla", 5, 6, ["all_year", "childrens_day"]),
    ("topper na tort", "cake topper", "Personalizowane", 10, 0.5, "pla", 3, 0, ["all_year"]),
    ("figurki d&d", "dnd miniatures", "Gaming", 10, 1.5, "pla", 5, 0, ["all_year"]),
    ("wieża do kości", "dice tower", "Gaming", 200, 9.0, "pla", 5, 0, ["all_year", "christmas"]),
    ("ozdoby choinkowe", "christmas ornament", "Święta", 12, 0.8, "pla", 1, 2, ["christmas"]),
    ("kalendarz adwentowy", "advent calendar", "Święta", 350, 14.0, "pla", 10, 0, ["christmas"]),
    ("choinka dekoracyjna", "christmas tree decoration", "Święta", 70, 4.0, "silk", 2, 0, ["christmas"]),
    ("dekoracje halloween", "halloween decor", "Święta", 60, 3.0, "pla", 2, 2, ["halloween"]),
    ("dynia halloween", "halloween pumpkin", "Święta", 80, 4.0, "pla", 2, 1, ["halloween"]),
    ("czaszka dekoracja", "skull decor", "Dekoracje", 90, 5.0, "pla", 3, 0, ["halloween", "all_year"]),
    ("pisanki", "easter egg", "Święta", 20, 1.0, "pla", 1, 2, ["easter"]),
    ("zajączek wielkanocny", "easter bunny", "Święta", 40, 2.0, "pla", 1, 0, ["easter"]),
    ("serce walentynki", "valentine heart", "Święta", 30, 1.5, "pla", 2, 0, ["valentines"]),
    ("zakładka do książki", "bookmark", "Szkoła", 5, 0.3, "pla", 1, 1, ["back_to_school", "christmas"]),
    ("przybornik na długopisy", "pen holder", "Szkoła", 60, 3.0, "pla", 1, 0, ["back_to_school"]),
    ("uchwyt na rower", "bike wall mount", "Sport", 120, 5.0, "petg", 2, 0, ["summer"]),
    ("karmnik dla ptaków", "bird feeder", "Ogród", 150, 6.0, "petg", 2, 0, ["christmas"]),
    ("stojak na biżuterię", "jewelry stand", "Dekoracje", 60, 3.0, "silk", 2, 0, ["valentines", "mothers_day", "christmas"]),
    ("mydelniczka", "soap dish", "Łazienka", 40, 1.5, "petg", 1, 0, ["all_year"]),
    ("abażur lampy", "lamp shade", "Dekoracje", 250, 10.0, "pla", 5, 0, ["all_year", "christmas"]),
    ("uchwyt na router", "router wall mount", "Dom i biuro", 70, 2.5, "pla", 1, 0, ["all_year"]),
    ("podkładki pod kubki", "coasters", "Kuchnia", 25, 1.2, "pla", 1, 3, ["all_year", "christmas"]),
]


def seed_rows() -> list[dict]:
    rows = []
    for pl, en, cat, w, t, fil, post, cc, seasons in SEED:
        rows.append({
            "keyword": pl, "keyword_en": en, "category": cat, "weight_g": w, "time_h": t,
            "filament": fil, "post_min": post, "color_changes": cc, "seasons": seasons,
        })
    return rows


# serwisy bez publicznego API: tylko szybkie linki do wyszukiwania
QUICK_LINKS = {
    "models": {
        "MakerWorld": "https://makerworld.com/en/search/models?keyword={q}",
        "Printables": "https://www.printables.com/search/models?q={q}",
        "Thangs": "https://thangs.com/search/{q}?scope=all",
        "Cults3D": "https://cults3d.com/en/search?q={q}",
        "Thingiverse": "https://www.thingiverse.com/search?q={q}&type=things&sort=popular",
    },
    "market": {
        "Allegro": "https://allegro.pl/listing?string={q}&order=qd",
        "OLX": "https://www.olx.pl/oferty/q-{q_dash}/",
        "Etsy": "https://www.etsy.com/search?q={q}",
        "Amazon.pl": "https://www.amazon.pl/s?k={q}",
        "eBay.de": "https://www.ebay.de/sch/i.html?_nkw={q}",
        "Vinted": "https://www.vinted.pl/catalog?search_text={q}",
    },
}
