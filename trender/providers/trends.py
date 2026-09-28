"""Google Trends: zainteresowanie frazą w czasie i rosnące powiązane zapytania."""

from __future__ import annotations

import asyncio

import httpx

from ..config import Settings
from ..schemas import TrendPoint, TrendSeries
from .base import ProviderError, dig, raise_for, to_float


def momentum(values: list[float], recent: int = 4, base: int = 12) -> tuple[float | None, float | None]:
    """(momentum, level): średnia ostatnich `recent` punktów vs `base` wcześniejszych."""
    vals = [v for v in values if v is not None]
    if len(vals) < recent + 2:
        return None, None
    last = vals[-recent:]
    prev = vals[-(recent + base):-recent] or vals[:-recent]
    level = sum(last) / len(last)
    prev_avg = sum(prev) / len(prev)
    if prev_avg <= 0:
        return (1.0 if level > 0 else 0.0), level
    return level / prev_avg - 1, level


class SerpApiTrends:
    name = "google_trends"
    label = "Google Trends (SerpApi)"
    URL = "https://serpapi.com/search.json"

    def __init__(self, s: Settings):
        self.key, self.geo = s.serpapi_key, s.trends_geo

    @property
    def configured(self) -> bool:
        return bool(self.key)

    async def interest(self, client: httpx.AsyncClient, keyword: str) -> TrendSeries:
        r = await client.get(self.URL, params={"engine": "google_trends", "q": keyword, "geo": self.geo,
                                               "date": "today 12-m", "data_type": "TIMESERIES",
                                               "api_key": self.key})
        raise_for(r, "SerpApi")
        data = r.json()
        if data.get("error"):
            raise ProviderError(f"SerpApi: {data['error']}")
        points = []
        for row in dig(data, "interest_over_time", "timeline_data", default=[]) or []:
            v = to_float(dig(row, "values", 0, "extracted_value"))
            points.append(TrendPoint(date=str(row.get("date", "")), value=v or 0.0))
        m, lvl = momentum([p.value for p in points])
        return TrendSeries(keyword=keyword, source=self.name, points=points, momentum=m, level=lvl)

    async def rising(self, client: httpx.AsyncClient, keyword: str) -> list[dict]:
        r = await client.get(self.URL, params={"engine": "google_trends", "q": keyword, "geo": self.geo,
                                               "date": "today 3-m", "data_type": "RELATED_QUERIES",
                                               "api_key": self.key})
        raise_for(r, "SerpApi")
        rows = dig(r.json(), "related_queries", "rising", default=[]) or []
        return [{"query": x.get("query"), "growth": x.get("value")} for x in rows]


class PyTrends:
    """Nieoficjalna biblioteka pytrends. Działa bez klucza, ale Google często zwraca HTTP 429."""

    name = "google_trends"
    label = "Google Trends (pytrends)"

    def __init__(self, s: Settings):
        self.enabled, self.geo = s.pytrends_enabled, s.trends_geo
        try:
            import pytrends  # noqa: F401
            self.available = True
        except ImportError:
            self.available = False

    @property
    def configured(self) -> bool:
        return self.enabled and self.available

    def _req(self):
        from pytrends.request import TrendReq
        return TrendReq(hl="pl-PL", tz=60, retries=2, backoff_factor=0.5)

    def _interest_sync(self, keyword: str) -> list[TrendPoint]:
        req = self._req()
        req.build_payload([keyword], timeframe="today 12-m", geo=self.geo)
        df = req.interest_over_time()
        if df is None or df.empty:
            return []
        return [TrendPoint(date=idx.strftime("%Y-%m-%d"), value=float(v)) for idx, v in df[keyword].items()]

    def _rising_sync(self, keyword: str) -> list[dict]:
        req = self._req()
        req.build_payload([keyword], timeframe="today 3-m", geo=self.geo)
        rel = req.related_queries().get(keyword, {}) or {}
        df = rel.get("rising")
        if df is None or df.empty:
            return []
        return [{"query": row["query"], "growth": int(row["value"])} for _, row in df.iterrows()]

    async def interest(self, client: httpx.AsyncClient, keyword: str) -> TrendSeries:
        try:
            points = await asyncio.to_thread(self._interest_sync, keyword)
        except Exception as e:  # noqa: BLE001 - pytrends rzuca różne wyjątki
            raise ProviderError(f"pytrends: {e}") from e
        m, lvl = momentum([p.value for p in points])
        return TrendSeries(keyword=keyword, source=self.name, points=points, momentum=m, level=lvl)

    async def rising(self, client: httpx.AsyncClient, keyword: str) -> list[dict]:
        try:
            return await asyncio.to_thread(self._rising_sync, keyword)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"pytrends: {e}") from e


def trend_providers(s: Settings) -> list:
    """SerpApi ma pierwszeństwo (stabilne), pytrends jako zapas."""
    return [p for p in (SerpApiTrends(s), PyTrends(s)) if p.configured]
