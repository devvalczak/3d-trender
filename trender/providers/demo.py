"""Dane demonstracyjne (oznaczone jako DEMO), gdy nie skonfigurowano żadnego prawdziwego źródła.

Dane są deterministyczne dla danej frazy, żeby dało się przetestować cały przepływ aplikacji.
NIE są prawdziwymi danymi rynkowymi.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import random

from ..catalog import SEED
from ..schemas import Listing, MarketResult, ModelHit, TrendPoint, TrendSeries
from ..seasonality import events_for_year
from .trends import momentum

_CATALOG = {row[0]: row for row in SEED} | {row[1]: row for row in SEED}


def _rng(*parts: str) -> random.Random:
    h = hashlib.sha256("|".join(parts).lower().encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def _dims(query: str) -> tuple[float, float, float, int]:
    from ..catalog import DEFAULT_DIMS, DIMS
    row = _CATALOG.get(query.lower())
    return DIMS.get(row[0], DEFAULT_DIMS) if row else DEFAULT_DIMS


def _profile(query: str) -> tuple[float, float, list[str]]:
    row = _CATALOG.get(query.lower())
    if row:
        return row[3], row[4], row[8]
    r = _rng("profile", query)
    return r.uniform(15, 200), r.uniform(0.7, 8), ["all_year"]


class DemoMarket:
    def __init__(self, name: str, label: str, currency: str = "PLN", fx: float = 1.0):
        self.name, self.label, self.currency, self.fx = name, label, currency, fx
        self.configured = True

    async def search(self, client, query: str, limit: int = 40) -> MarketResult:
        r = _rng(self.name, query)
        weight, hours, _ = _profile(query)
        base = (12 + weight * 0.18 + hours * 4.5) * r.uniform(0.8, 1.5)
        total = int(r.lognormvariate(5.5, 1.1))
        listings = []
        for i in range(min(limit, 24)):
            price = max(4.99, round(base * r.lognormvariate(0, 0.35), 0) - 0.01)
            listings.append(Listing(
                source=self.name, title=f"[DEMO] {query} #{i + 1}", price=round(price / self.fx, 2),
                currency=self.currency, url=None, seller=f"demo_seller_{r.randint(1, 60)}",
                sold=int(r.expovariate(1 / 25)) if self.name == "allegro" else None,
                favorites=int(r.expovariate(1 / 120)) if self.name == "etsy" else None, demo=True,
            ))
        return MarketResult(source=self.name, query=query, total=total, listings=listings, demo=True)


class DemoTrends:
    name = "google_trends"
    label = "Google Trends (DEMO)"
    configured = True

    async def interest(self, client, keyword: str) -> TrendSeries:
        r = _rng("trend", keyword)
        _, _, seasons = _profile(keyword)
        today = dt.date.today()
        start = today - dt.timedelta(weeks=52)
        base = r.uniform(25, 60)
        growth = r.uniform(-0.3, 0.6)
        events = [e for y in (today.year - 1, today.year) for e in events_for_year(y) if e.tag in seasons]
        points = []
        for w in range(52):
            day = start + dt.timedelta(weeks=w)
            v = base * (1 + growth * w / 52)
            for e in events:
                d = (e.date - day).days
                if -7 <= d <= 60:
                    v += 45 * math.exp(-((d - 12) / 18) ** 2)
            v *= r.uniform(0.85, 1.15)
            points.append(TrendPoint(date=day.isoformat(), value=v))
        peak = max(p.value for p in points) or 1
        points = [TrendPoint(date=p.date, value=round(100 * p.value / peak)) for p in points]
        m, lvl = momentum([p.value for p in points])
        return TrendSeries(keyword=keyword, source=self.name, points=points, momentum=m, level=lvl, demo=True)

    async def rising(self, client, keyword: str) -> list[dict]:
        r = _rng("rising", keyword)
        picks = r.sample(_DEMO_RISING, 6)
        return [{"query": p, "growth": r.choice([50, 80, 120, 250, 400, "Breakout"])} for p in picks]


_DEMO_RISING = [
    "insert do gry planszowej", "magnetyczny organizer na przyprawy", "lampka nocna z imieniem",
    "labubu breloczek", "podstawka pod airpods", "wieszak na czapki", "organizer na filamenty",
    "uchwyt na suszarkę dyson", "pudełko na karty pokemon", "ozdoba na choinkę ze zdjęciem",
]


_DEMO_LICENSES = [
    ("Creative Commons - Attribution", None, 0.0),
    ("Creative Commons - Attribution - Non-Commercial", None, 0.0),
    ("Standard Digital File License", None, 0.0),
    ("CC0 - Public Domain", None, 0.0),
    ("Cults - Commercial Use", "cults_cu", 3.5),
    ("Creative Commons - Attribution - No Derivatives", None, 0.0),
    ("Private use only", "cults_private", 2.0),
]


class DemoModels:
    name = "demo_models"
    label = "Modele (DEMO)"
    configured = True

    async def search(self, client, query: str, limit: int = 20) -> list[ModelHit]:
        r = _rng("models", query)
        weight, hours, _ = _profile(query)
        dx, dy, dz, colors = _dims(query)
        out = []
        for i in range(min(limit, 10)):
            lic, code, price = _DEMO_LICENSES[r.randrange(len(_DEMO_LICENSES))]
            k = r.uniform(0.8, 1.17)
            w = weight * k ** 3
            out.append(ModelHit(
                source=self.name, id=f"demo-{i}", title=f"[DEMO] {query.title()} v{i + 1}", url=None,
                author=f"designer_{r.randint(1, 99)}", likes=int(r.expovariate(1 / 400)),
                downloads=int(r.expovariate(1 / 2500)), license_raw=lic, license_code=code,
                file_price=price, file_currency="EUR",
                commercial_license_cost_pln=r.choice([None, 20.0, 45.0]) if "Non-Commercial" in lic else None,
                est_weight_g=round(w, 1), est_time_h=round(hours * w / weight, 2),
                size_mm=[round(dx * k), round(dy * k), round(dz * k)], colors=colors, size_source="DEMO", demo=True,
            ))
        return out


def demo_markets() -> list:
    return [DemoMarket("allegro", "Allegro (DEMO)"), DemoMarket("olx", "OLX (DEMO)"),
            DemoMarket("etsy", "Etsy (DEMO)", "USD", 3.7), DemoMarket("ebay", "eBay (DEMO)", "EUR", 4.25)]
