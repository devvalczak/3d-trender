"""Wykrywanie ryzyka naruszenia znaków towarowych / praw autorskich w frazach i tytułach.

Wydruki z postaciami z gier, filmów czy logo marek to najczęstszy powód blokad kont
na Allegro/Etsy i wezwań do zapłaty, nawet jeśli model jest darmowy.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

HIGH = [
    "pokemon", "pokémon", "pikachu", "disney", "marvel", "star wars", "mandalorian", "grogu", "baby yoda",
    "harry potter", "hogwarts", "nintendo", "mario", "zelda", "minecraft", "fortnite", "lego", "stitch",
    "hello kitty", "sanrio", "batman", "spiderman", "spider-man", "dc comics", "warhammer", "naruto",
    "one piece", "dragon ball", "genshin", "among us", "sonic", "labubu", "squid game", "bluey",
    "peppa", "psi patrol", "paw patrol", "frozen", "kraina lodu", "shrek", "minionki", "minions",
    "ferrari", "porsche", "lamborghini", "formula 1", "f1 logo", "nike", "adidas", "real madryt",
    "fc barcelona", "legia", "nfl", "nba", "fifa", "uefa", "wiedźmin", "witcher", "cyberpunk",
    "stranger things", "wednesday", "barbie", "hot wheels", "transformers", "gwiezdne wojny",
]
# nazwy marek, zwykle dopuszczalne w formie "kompatybilny z ..." bez logo
MEDIUM = [
    "ps5", "ps4", "playstation", "xbox", "iphone", "airpods", "apple", "samsung", "dyson", "stanley",
    "ikea", "tesla", "bmw", "audi", "mercedes", "toyota", "jeep", "gopro", "nespresso", "tefal",
    "thermomix", "switch", "steam deck", "garmin",
]


class IpRisk(BaseModel):
    level: str  # none / medium / high
    hits: list[str]
    note: str = ""


def _find(text: str, words: list[str]) -> list[str]:
    return [w for w in words if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", text)]


def check_ip(*texts: str | None) -> IpRisk:
    text = " ".join(t for t in texts if t).lower()
    high = _find(text, HIGH)
    if high:
        return IpRisk(level="high", hits=high,
                      note="Chroniona postać/marka: sprzedaż bez licencji grozi blokadą konta i roszczeniami.")
    med = _find(text, MEDIUM)
    if med:
        return IpRisk(level="medium", hits=med,
                      note="Nazwa marki: pisz 'kompatybilny z ...', nie używaj logo ani zdjęć producenta.")
    return IpRisk(level="none", hits=[])


def ip_multiplier(risk: IpRisk) -> float:
    return {"none": 1.0, "medium": 0.9, "high": 0.3}[risk.level]
