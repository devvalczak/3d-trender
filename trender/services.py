"""Logika aplikacji: łączy dostawców, cache, kalkulator i scoring."""

from __future__ import annotations

import asyncio
import datetime as dt
import time

import httpx

from .config import Settings
from .costing import CostInput, calculate
from .currency import rates
from .db import Store
from .ip_risk import check_ip
from .licensing import classify_license, license_score
from .providers.base import make_client
from .providers.demo import DemoModels, DemoTrends, demo_markets
from .providers.markets import market_providers
from .providers.models import model_providers
from .providers.trends import trend_providers
from .schemas import Listing, MarketResult, ModelHit
from .scoring import market_stats, model_score, opportunity_score
from .seasonality import season_boost

EN_MARKETS = {"etsy", "ebay"}  # rynki, na których szukamy frazą angielską


def _resolve(real: list, demo: list, mode: str) -> list:
    if mode == "on":
        return demo
    configured = [p for p in real if p.configured]
    if mode == "off":
        return configured
    return configured or demo


class Services:
    def __init__(self, settings: Settings, store: Store, client: httpx.AsyncClient | None = None):
        self.s = settings
        self.store = store
        self._client = client
        self.markets = _resolve(market_providers(settings), demo_markets(), settings.demo_mode)
        self.trends = _resolve(trend_providers(settings), [DemoTrends()], settings.demo_mode)
        self.models = _resolve(model_providers(settings), [DemoModels()], settings.demo_mode)
        self.scan_state: dict = {"running": False, "done": 0, "total": 0, "errors": [], "finished_at": None}

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_client()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def status(self) -> dict:
        def info(p):
            return {"name": p.name, "label": p.label, "demo": "DEMO" in p.label}
        return {
            "demo_mode": self.s.demo_mode,
            "markets": [info(p) for p in self.markets],
            "trends": [info(p) for p in self.trends],
            "models": [info(p) for p in self.models],
            "fx_live": rates.live,
        }

    # ------------------------------------------------------------ rynek / konkurencja
    async def _market_one(self, p, query: str) -> MarketResult:
        try:
            return await p.search(self.client, query)
        except Exception as e:  # noqa: BLE001 - błąd jednego źródła nie może zatrzymać reszty
            return MarketResult(source=p.name, query=query, error=str(e)[:300])

    async def market(self, query: str, query_en: str | None = None, use_cache: bool = True) -> dict:
        key = f"market:{query}|{query_en or ''}|{','.join(p.name for p in self.markets)}"
        if use_cache and (hit := self.store.cache_get(key)):
            return hit
        await rates.refresh(self.client)
        results = await asyncio.gather(*(
            self._market_one(p, (query_en or query) if p.name in EN_MARKETS else query) for p in self.markets))

        listings: list[Listing] = []
        sources = []
        for p, res in zip(self.markets, results):
            for l in res.listings:
                l.price_pln = rates.to_pln(l.price, l.currency)
            listings += res.listings
            sources.append({"source": p.name, "label": p.label, "query": res.query, "total": res.total,
                            "count": len(res.listings), "error": res.error, "demo": res.demo,
                            "stats": market_stats(res.listings)})
        listings.sort(key=lambda l: l.price_pln or 0)
        totals = [s["total"] for s in sources if s["total"] is not None]
        out = {
            "query": query, "query_en": query_en, "fetched_at": time.time(),
            "sources": sources, "stats": market_stats(listings),
            "total_listings": sum(totals) if totals else None,
            "listings": [l.model_dump() for l in listings],
        }
        if any(s["error"] is None for s in sources):
            self.store.cache_set(key, out, self.s.market_cache_hours * 3600)
        return out

    def reference_price(self, market: dict, channel: str) -> tuple[float | None, str]:
        """Mediana ceny z kanału sprzedaży, a gdy jej brak, z polskich rynków lub z całości."""
        by = {s["source"]: s for s in market["sources"]}
        if (st := by.get(channel, {}).get("stats", {})).get("median"):
            return st["median"], by[channel]["label"]
        pl = [l["price_pln"] for l in market["listings"] if l["source"] in ("allegro", "olx") and l["price_pln"]]
        if pl:
            pl.sort()
            return pl[len(pl) // 2], "rynek PL"
        med = market["stats"].get("median")
        return med, "wszystkie rynki"

    # ------------------------------------------------------------ trendy
    async def trend(self, keyword: str, use_cache: bool = True) -> dict:
        key = f"trend:{keyword}|{','.join(p.label for p in self.trends)}"
        if use_cache and (hit := self.store.cache_get(key)):
            return hit
        errors = []
        for p in self.trends:
            try:
                series = (await p.interest(self.client, keyword)).model_dump()
                self.store.cache_set(key, series, 24 * 3600)
                return series
            except Exception as e:  # noqa: BLE001
                errors.append(str(e)[:200])
        return {"keyword": keyword, "source": None, "points": [], "momentum": None, "level": None,
                "error": "; ".join(errors) or "Brak skonfigurowanego źródła trendów", "demo": False}

    async def discover(self, seeds: list[str]) -> list[dict]:
        """Rosnące zapytania powiązane z frazami-nasionami: kandydaci do obserwowania."""
        known = {k["keyword"].lower() for k in self.store.list_keywords()}
        out: dict[str, dict] = {}
        for seed in seeds:
            key = f"rising:{seed}|{','.join(p.label for p in self.trends)}"
            rows = self.store.cache_get(key)
            if rows is None:
                rows = []
                for p in self.trends:
                    try:
                        rows = await p.rising(self.client, seed)
                        break
                    except Exception:  # noqa: BLE001
                        continue
                self.store.cache_set(key, rows, 24 * 3600)
            for r in rows:
                q = (r.get("query") or "").strip()
                if q and q.lower() not in known and q.lower() not in out:
                    out[q.lower()] = {"query": q, "growth": r.get("growth"), "seed": seed,
                                      "ip": check_ip(q).model_dump()}
        return list(out.values())

    # ------------------------------------------------------------ okazje
    async def evaluate_keyword(self, kw: dict, use_cache: bool = True) -> dict:
        profile = self.store.get_profile()
        market, trend = await asyncio.gather(self.market(kw["keyword"], kw.get("keyword_en"), use_cache),
                                             self.trend(kw["keyword"], use_cache))
        cost_in = CostInput(weight_g=kw["weight_g"], print_time_h=kw["time_h"], filament_id=kw.get("filament"),
                            post_processing_min=kw.get("post_min") or 0, color_changes=kw.get("color_changes") or 0)
        ref_price, ref_label = self.reference_price(market, profile.default_channel)
        cost_in.sale_price_pln = ref_price
        calc = calculate(cost_in, profile)
        boost, season_name = season_boost(kw.get("seasons") or ["all_year"])
        ip = check_ip(kw["keyword"], kw.get("keyword_en"))
        at = calc.at_price
        sc = opportunity_score(
            total_listings=market["total_listings"], sold_sum=market["stats"].get("sold_sum"),
            favorites_avg=market["stats"].get("favorites_avg"), trend_momentum=trend.get("momentum"),
            trend_level=trend.get("level"), season_boost=boost, season_name=season_name,
            profit_per_hour=at.profit_per_hour if at else None, profit=at.profit if at else None,
            market_price=ref_price, ip=ip, profile=profile,
        )
        result = {
            "keyword_id": kw["id"], "keyword": kw["keyword"], "keyword_en": kw.get("keyword_en"),
            "category": kw.get("category"), **sc,
            "market": {"total_listings": market["total_listings"], "stats": market["stats"],
                       "reference_price": ref_price, "reference": ref_label,
                       "sources": [{k: s[k] for k in ("source", "label", "total", "count", "error", "demo")}
                                   for s in market["sources"]]},
            "trend": {"momentum": trend.get("momentum"), "level": trend.get("level"), "error": trend.get("error"),
                      "spark": [p["value"] for p in trend.get("points", [])][-26:], "demo": trend.get("demo")},
            "season": {"boost": round(boost, 2), "event": season_name},
            "cost": calc.cost.model_dump(), "suggested": calc.suggested.model_dump(),
            "at_market": at.model_dump() if at else None,
            "ip": ip.model_dump(),
            "demo": any(s["demo"] for s in market["sources"]) or bool(trend.get("demo")),
        }
        self.store.save_opportunity(kw["id"], result)
        self.store.record_history(kw["keyword"], dt.date.today().isoformat(), market["total_listings"],
                                  ref_price, market["stats"].get("sold_sum"), trend.get("level"))
        return result

    async def scan(self, keyword_ids: list[int] | None = None, use_cache: bool = True) -> None:
        if self.scan_state["running"]:
            return
        kws = [k for k in self.store.list_keywords(active_only=True) if not keyword_ids or k["id"] in keyword_ids]
        self.scan_state = {"running": True, "done": 0, "total": len(kws), "errors": [], "finished_at": None}
        sem = asyncio.Semaphore(3)  # szanujemy limity API

        async def one(kw):
            async with sem:
                try:
                    await self.evaluate_keyword(kw, use_cache)
                except Exception as e:  # noqa: BLE001
                    self.scan_state["errors"].append(f"{kw['keyword']}: {e}")
                self.scan_state["done"] += 1

        try:
            await asyncio.gather(*(one(k) for k in kws))
        finally:
            self.scan_state.update(running=False, finished_at=time.time())

    def opportunities(self, sort: str = "score", category: str | None = None) -> list[dict]:
        items = self.store.list_opportunities()
        if category:
            items = [i for i in items if i.get("category") == category]
        keys = {
            "score": lambda i: i["score"],
            "profit_h": lambda i: (i.get("at_market") or {}).get("profit_per_hour") or -1e9,
            "profit": lambda i: (i.get("at_market") or {}).get("profit") or -1e9,
            "demand": lambda i: i["subscores"]["demand"],
            "trend": lambda i: i["trend"].get("momentum") or -1e9,
            "season": lambda i: i["season"]["boost"],
        }
        return sorted(items, key=keys.get(sort, keys["score"]), reverse=True)

    # ------------------------------------------------------------ modele 3D
    async def _models_one(self, p, query: str) -> tuple[list[ModelHit], str | None]:
        try:
            return await p.search(self.client, query), None
        except Exception as e:  # noqa: BLE001
            return [], str(e)[:300]

    def _match_keyword(self, query: str) -> dict | None:
        q = query.lower().strip()
        kws = self.store.list_keywords()
        for k in kws:
            if q in (k["keyword"].lower(), (k.get("keyword_en") or "").lower()):
                return k
        for k in kws:
            if k["keyword"].lower() in q or (k.get("keyword_en") and k["keyword_en"].lower() in q):
                return k
        if len(q) >= 4:
            for k in kws:
                if q in k["keyword"].lower() or q in (k.get("keyword_en") or "").lower():
                    return k
        return None

    async def search_models(self, query: str, *, commercial_only: bool = False,
                            max_license_cost: float | None = None, sort: str = "score",
                            with_market: bool = True, weight_g: float | None = None,
                            time_h: float | None = None, filament: str | None = None) -> dict:
        profile = self.store.get_profile()
        await rates.refresh(self.client)
        kw = self._match_keyword(query)
        results = await asyncio.gather(*(self._models_one(p, query) for p in self.models))
        market = await self.market(query, kw.get("keyword_en") if kw else None) if with_market else None
        ref_price, ref_label = self.reference_price(market, profile.default_channel) if market else (None, "")

        default_w = weight_g or (kw["weight_g"] if kw else 50.0)
        default_t = time_h or (kw["time_h"] if kw else 2.0)
        hits = []
        for p, (items, _err) in zip(self.models, results):
            for h in items:
                h.license = classify_license(h.license_raw, h.license_code)
                h.file_price_pln = rates.to_pln(h.file_price or 0.0, h.file_currency) or 0.0
                if h.license.commercial_ok:
                    license_total = h.file_price_pln
                elif h.commercial_license_cost_pln is not None:
                    license_total = h.file_price_pln + h.commercial_license_cost_pln
                    h.license = h.license.model_copy(update={
                        "status": "paid", "label": "Licencja komercyjna płatna",
                        "note": f"Licencja komercyjna: ok. {h.commercial_license_cost_pln:.0f} zł"})
                else:
                    license_total = None  # nie da się legalnie sprzedawać bez kontaktu z autorem

                if commercial_only and license_total is None:
                    continue
                if max_license_cost is not None and (license_total or 0) > max_license_cost:
                    continue

                w = weight_g or h.est_weight_g or default_w
                t = time_h or h.est_time_h or default_t
                calc = calculate(CostInput(weight_g=w, print_time_h=t, filament_id=filament or (kw or {}).get("filament"),
                                           license_cost_pln=license_total or 0, sale_price_pln=ref_price,
                                           post_processing_min=(kw or {}).get("post_min") or 0), profile)
                at = calc.at_price
                ip = check_ip(h.title, query)
                hits.append({
                    **h.model_dump(), "license_total_pln": license_total,
                    "weight_g": round(w, 1), "time_h": round(t, 2),
                    "weight_source": "model" if h.est_weight_g and not weight_g else
                                     ("ręcznie" if weight_g else ("katalog" if kw else "domyślne")),
                    "cost": calc.cost.model_dump(), "suggested": calc.suggested.model_dump(),
                    "at_market": at.model_dump() if at else None, "ip": ip.model_dump(),
                    "score": model_score(profit_per_hour=at.profit_per_hour if at else None, likes=h.likes,
                                         downloads=h.downloads,
                                         license_s=license_score(h.license, license_total), ip=ip, profile=profile),
                })
        keys = {
            "score": lambda x: x["score"],
            "profit_h": lambda x: (x["at_market"] or {}).get("profit_per_hour") or -1e9,
            "profit": lambda x: (x["at_market"] or {}).get("profit") or -1e9,
            "popularity": lambda x: (x["likes"] or 0) + (x["downloads"] or 0) / 10,
            "cost": lambda x: -x["cost"]["total"],
        }
        hits.sort(key=keys.get(sort, keys["score"]), reverse=True)
        return {
            "query": query, "matched_keyword": kw["keyword"] if kw else None,
            "reference_price": ref_price, "reference": ref_label,
            "sources": [{"source": p.name, "label": p.label, "count": len(items), "error": err}
                        for p, (items, err) in zip(self.models, results)],
            "hits": hits,
        }
