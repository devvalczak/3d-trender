"""Ocena opłacalności: łączy popyt, konkurencję, marżę i sezon w jeden wynik 0-100.

Każdy wynik ma listę powodów ("reasons"), żeby było jasne, skąd się wziął.
"""

from __future__ import annotations

import math
import statistics

from .ip_risk import IpRisk, ip_multiplier
from .profile import Profile
from .schemas import Listing


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def norm_log(x: float | None, lo: float, hi: float) -> float:
    if x is None or x <= 0:
        return 0.0
    return clamp((math.log10(x) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)))


def market_stats(listings: list[Listing]) -> dict:
    prices = sorted(l.price_pln for l in listings if l.price_pln)
    sold = [l.sold for l in listings if l.sold is not None]
    favs = [l.favorites for l in listings if l.favorites is not None]
    if not prices:
        return {"count": 0}
    q = statistics.quantiles(prices, n=4) if len(prices) >= 2 else [prices[0]] * 3
    return {
        "count": len(prices),
        "min": round(prices[0], 2), "p25": round(q[0], 2), "median": round(statistics.median(prices), 2),
        "p75": round(q[2], 2), "max": round(prices[-1], 2), "mean": round(statistics.fmean(prices), 2),
        "sold_sum": sum(sold) if sold else None,
        "favorites_avg": round(statistics.fmean(favs), 1) if favs else None,
    }


def tier(score: float) -> dict:
    if score >= 72:
        return {"id": "best", "label": "Najlepsze", "rank": 3}
    if score >= 58:
        return {"id": "better", "label": "Bardzo dobre", "rank": 2}
    if score >= 45:
        return {"id": "good", "label": "Dobre", "rank": 1}
    return {"id": "weak", "label": "Słabe", "rank": 0}


def pln(x: float) -> str:
    return f"{x:,.2f} zł".replace(",", " ").replace(".", ",")


def opportunity_score(*, total_listings: int | None, sold_sum: int | None, favorites_avg: float | None,
                      trend_momentum: float | None, trend_level: float | None, season_boost: float,
                      season_name: str | None, profit_per_hour: float | None, profit: float | None,
                      market_price: float | None, ip: IpRisk, profile: Profile) -> dict:
    reasons: list[str] = []

    # --- popyt
    parts: list[tuple[float, float]] = []
    if sold_sum is not None:
        parts.append((0.4, norm_log(sold_sum + 1, 1, 500)))
        reasons.append(f"Sprzedaż konkurencji (top oferty, 30 dni): {sold_sum} szt.")
    if trend_momentum is not None:
        parts.append((0.3, clamp((trend_momentum + 0.3) / 0.9)))
        sign = "+" if trend_momentum >= 0 else ""
        reasons.append(f"Trend wyszukiwań: {sign}{trend_momentum * 100:.0f}% vs poprzednie 3 miesiące")
    if trend_level is not None:
        parts.append((0.15, clamp(trend_level / 100)))
    if favorites_avg is not None:
        parts.append((0.15, norm_log(favorites_avg + 1, 1, 300)))
    demand = sum(w * v for w, v in parts) / sum(w for w, _ in parts) if parts else 0.5
    if not parts:
        reasons.append("Brak danych o popycie (podłącz Allegro / Google Trends)")

    # --- konkurencja
    if total_listings is not None:
        competition = 1 - norm_log(total_listings, 20, 20000)
        reasons.append(f"Konkurencja: {total_listings} ofert")
    else:
        competition = 0.5

    # --- marża
    if profit_per_hour is not None and market_price is not None:
        margin = clamp(profit_per_hour / profile.target_profit_per_hour_pln)
        reasons.append(f"Mediana ceny {pln(market_price)}, zysk {pln(profit or 0)}/szt., {pln(profit_per_hour)}/h drukarki")
    else:
        margin = 0.4
        reasons.append("Brak cen konkurencji: marża nieznana")

    # --- sezon
    if season_name and season_boost >= 0.5:
        reasons.append(f"Sezon: {season_name} (teraz jest dobry moment)")
    elif season_name and season_boost > 0:
        reasons.append(f"Sezon: {season_name} zbliża się, przygotuj zapas")

    w = profile.weights
    total_w = w.margin + w.demand + w.competition + w.season
    raw = (w.margin * margin + w.demand * demand + w.competition * competition + w.season * season_boost) / total_w
    score = raw * 100 * ip_multiplier(ip)
    if ip.level != "none":
        reasons.append(f"Ryzyko IP ({ip.level}): {', '.join(ip.hits)}")
    if profit is not None and profit <= 0:
        score = min(score, 30)
        reasons.append("Przy cenach rynkowych sprzedaż jest nieopłacalna")

    score = round(score, 1)
    return {
        "score": score, "tier": tier(score),
        "subscores": {"demand": round(demand * 100), "competition": round(competition * 100),
                      "margin": round(margin * 100), "season": round(season_boost * 100)},
        "reasons": reasons,
    }


def model_score(*, profit_per_hour: float | None, likes: int | None, downloads: int | None,
                license_s: float, ip: IpRisk, profile: Profile) -> float:
    margin = clamp(profit_per_hour / profile.target_profit_per_hour_pln) if profit_per_hour is not None else 0.4
    pop = norm_log((likes or 0) + (downloads or 0) / 10 + 1, 1, 5000)
    return round(100 * (0.45 * margin + 0.25 * pop + 0.30 * license_s) * ip_multiplier(ip), 1)
