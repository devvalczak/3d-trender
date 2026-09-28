"""Klasyfikacja licencji modeli 3D pod kątem sprzedaży wydruków.

To heurystyka, nie porada prawna: przed sprzedażą zawsze sprawdź licencję na stronie modelu.
"""

from __future__ import annotations

import re

from .schemas import LicenseInfo

_LABELS = {
    "allowed": "Komercyjnie OK",
    "attribution": "Komercyjnie OK (podaj autora)",
    "no_derivatives": "Komercyjnie OK bez modyfikacji",
    "paid": "Licencja komercyjna płatna",
    "non_commercial": "Tylko użytek prywatny",
    "unknown": "Nieznana: sprawdź ręcznie",
}

# kody licencji używane przez serwisy (np. Cults3D)
_CODE_MAP = {
    "cults_cu": "allowed",
    "cults_commercial": "allowed",
    "cults_private": "non_commercial",
    "cults_ncu": "non_commercial",
    "cc0": "allowed",
    "public_domain": "allowed",
}


def _norm(text: str) -> str:
    t = text.lower().replace("_", "-")
    t = re.sub(r"[‐-―]", "-", t)
    return re.sub(r"\s+", " ", t).strip()


def classify_license(raw: str | None, code: str | None = None) -> LicenseInfo:
    status = "unknown"
    if code and code.lower() in _CODE_MAP:
        status = _CODE_MAP[code.lower()]
    elif raw:
        t = _norm(raw)
        compact = t.replace(" ", "")
        if any(s in compact for s in ("noncommercial", "non-commercial", "by-nc", "cc-nc", "ccbync")) \
                or re.search(r"\bnc\b", t) or "personal use" in t or "private use" in t \
                or "standard digital file" in t or "all rights reserved" in t or "uso personal" in t:
            status = "non_commercial"
        elif "cc0" in compact or "public domain" in t or "creative commons zero" in t:
            status = "allowed"
        elif "commercial" in t and ("paid" in t or "purchase" in t or "sold separately" in t):
            status = "paid"
        elif "commercial" in t:
            status = "allowed"
        elif "noderiv" in compact or "no deriv" in t or "by-nd" in compact or re.search(r"\bnd\b", t):
            status = "no_derivatives"
        elif any(s in t for s in ("attribution", "cc-by", "cc by", "gpl", "gnu", "bsd", "mit license")) \
                or re.fullmatch(r"(cc[- ]?)?by([- ]sa)?( [\d.]+)?", t) or t == "mit":
            status = "attribution"

    note = {
        "attribution": "Wymagane podanie autora (np. w opisie aukcji).",
        "no_derivatives": "Możesz sprzedawać wydruki, ale nie modyfikuj modelu.",
        "non_commercial": "Zapytaj autora o licencję komercyjną (często Patreon / członkostwo / jednorazowa opłata).",
        "paid": "Kup licencję komercyjną u autora.",
        "unknown": "Brak jednoznacznej licencji: sprawdź stronę modelu przed sprzedażą.",
    }.get(status, "")
    return LicenseInfo(status=status, commercial_ok=status in ("allowed", "attribution", "no_derivatives"),
                       label=_LABELS[status], note=note)


def license_score(info: LicenseInfo, license_cost_pln: float | None = None) -> float:
    """0-1: jak "czysta" jest ścieżka do legalnej sprzedaży."""
    return {
        "allowed": 1.0,
        "attribution": 0.95,
        "no_derivatives": 0.85,
        "paid": 0.7 if license_cost_pln is not None else 0.5,
        "unknown": 0.35,
        "non_commercial": 0.1,
    }[info.status]
