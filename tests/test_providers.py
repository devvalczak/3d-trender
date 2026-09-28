"""Dostawcy testowani na zamockowanych odpowiedziach HTTP (kształt wg dokumentacji API)."""

import asyncio
import json

import httpx
import pytest

from trender.config import Settings
from trender.db import Store
from trender.providers.markets import AllegroProvider, EbayProvider, EtsyProvider, OlxProvider
from trender.providers.models import Cults3DProvider, PrintablesProvider, ThingiverseProvider
from trender.providers.trends import SerpApiTrends, momentum
from trender.services import Services

S = Settings(_env_file=None, allegro_client_id="id", allegro_client_secret="sec", ebay_client_id="e",
             ebay_client_secret="s", etsy_api_key="k", etsy_shared_secret="ss", serpapi_key="x",
             thingiverse_token="t", cults3d_username="u", cults3d_api_key="k", demo_mode="off",
             pytrends_enabled=False, olx_enabled=True, printables_enabled=True, refresh_interval_hours=0)


def handler(req: httpx.Request) -> httpx.Response:
    u = str(req.url)
    if "allegro.pl/auth/oauth/token" in u:
        assert req.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json={"access_token": "A", "expires_in": 3600})
    if "api.allegro.pl/offers/listing" in u:
        assert req.headers["authorization"] == "Bearer A"
        assert req.url.params["phrase"] == "organizer"
        return httpx.Response(200, json={
            "items": {"promoted": [{"id": "1", "name": "Organizer A", "seller": {"login": "s1"},
                                    "sellingMode": {"price": {"amount": "39.99", "currency": "PLN"}, "popularity": 12}}],
                      "regular": [{"id": "2", "name": "Organizer B",
                                   "sellingMode": {"price": {"amount": "59.00", "currency": "PLN"}}}]},
            "searchMeta": {"availableCount": 250, "totalCount": 250}})
    if "olx.pl/api/v1/offers" in u:
        return httpx.Response(200, json={"data": [
            {"title": "Organizer OLX", "url": "https://www.olx.pl/d/x", "params": [{"key": "price", "value": {"value": 45, "currency": "PLN"}}]},
            {"title": "Za darmo", "params": [{"key": "price", "value": {"value": 0}}]}],
            "metadata": {"total_elements": 31}})
    if "identity/v1/oauth2/token" in u:
        return httpx.Response(200, json={"access_token": "E", "expires_in": 7200})
    if "item_summary/search" in u:
        assert req.headers["x-ebay-c-marketplace-id"] == "EBAY_DE"
        assert req.url.params["q"] == "desk organizer"
        return httpx.Response(200, json={"total": 900, "itemSummaries": [
            {"title": "Desk org", "price": {"value": "10.00", "currency": "EUR"}, "itemWebUrl": "https://ebay.de/i/1"}]})
    if "openapi.etsy.com" in u:
        assert req.headers["x-api-key"] == "k:ss"
        return httpx.Response(200, json={"count": 5000, "results": [
            {"title": "Etsy org", "price": {"amount": 2500, "divisor": 100, "currency_code": "USD"}, "num_favorers": 80,
             "url": "https://etsy.com/l/1", "shop_id": 9}]})
    if "api.nbp.pl" in u:
        return httpx.Response(200, json=[{"rates": [{"code": "EUR", "mid": 4.3}, {"code": "USD", "mid": 3.8}]}])
    if "serpapi.com" in u:
        vals = [10] * 12 + [20] * 4
        return httpx.Response(200, json={"interest_over_time": {"timeline_data": [
            {"date": f"w{i}", "values": [{"extracted_value": v}]} for i, v in enumerate(vals)]}})
    if "api.thingiverse.com/search" in u:
        return httpx.Response(200, json={"total": 1, "hits": [{"id": 7, "name": "Thing", "public_url": "https://thingiverse.com/thing:7",
                                                                 "like_count": 50, "creator": {"name": "bob"}}]})
    if "api.thingiverse.com/things/7/files" in u:
        return httpx.Response(200, json=[{"id": 1, "name": "readme.txt", "size": 10},
                                         {"id": 2, "name": "small.stl", "size": 100, "download_url": "https://api.thingiverse.com/files/2/download"},
                                         {"id": 3, "name": "part.3mf", "size": 50, "download_url": "https://api.thingiverse.com/files/3/download"}])
    if "api.thingiverse.com/files/3/download" in u:
        assert req.headers["authorization"] == "Bearer t"
        return httpx.Response(200, content=b"3MFDATA")
    if "api.thingiverse.com/things/7" in u:
        return httpx.Response(200, json={"license": "Creative Commons - Attribution - Non-Commercial", "download_count": 900})
    if "cults3d.com/graphql" in u:
        body = json.loads(req.content)
        assert body["variables"]["q"] == "organizer"
        return httpx.Response(200, json={"data": {"creationsSearchBatch": {"total": 1, "results": [
            {"identifier": "c1", "name": "Cults org", "url": "https://cults3d.com/c1", "likesCount": 10, "downloadsCount": 100,
             "price": {"cents": 300}, "license": {"code": "cults_cu", "name": "Cults - Commercial Use"}, "creator": {"nick": "al"}}]}}})
    if "api.printables.com" in u:
        return httpx.Response(200, json={"errors": [{"message": "Cannot query field searchPrints2"}]})
    return httpx.Response(404, text="nope " + u)


def client():
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_allegro_parsing():
    async def go():
        async with client() as c:
            return await AllegroProvider(S).search(c, "organizer")
    r = run(go())
    assert r.total == 250 and [l.price for l in r.listings] == [39.99, 59.0]
    assert r.listings[0].sold == 12 and r.listings[0].url == "https://allegro.pl/oferta/1"


def test_other_markets():
    async def go():
        async with client() as c:
            return (await OlxProvider(S).search(c, "organizer"), await EbayProvider(S).search(c, "desk organizer"),
                    await EtsyProvider(S).search(c, "organizer"))
    olx, ebay, etsy = run(go())
    assert olx.total == 31 and len(olx.listings) == 1
    assert ebay.listings[0].currency == "EUR" and ebay.total == 900
    assert etsy.listings[0].price == 25.0 and etsy.listings[0].favorites == 80


def test_serpapi_momentum():
    async def go():
        async with client() as c:
            return await SerpApiTrends(S).interest(c, "organizer")
    t = run(go())
    assert t.momentum == pytest.approx(1.0) and t.level == 20
    assert momentum([1, 2]) == (None, None)


def test_models_parsing():
    async def go():
        async with client() as c:
            return await ThingiverseProvider(S).search(c, "organizer"), await Cults3DProvider(S).search(c, "organizer")
    thing, cults = run(go())
    assert thing[0].license_raw.endswith("Non-Commercial") and thing[0].downloads == 900
    assert cults[0].file_price == 3.0 and cults[0].license_code == "cults_cu"


def test_services_end_to_end_with_mocks(tmp_path):
    from trender.currency import rates
    rates.fetched = 0
    store = Store(str(tmp_path / "db.sqlite"))
    svc = Services(S, store, client=client())

    async def go():
        m = await svc.market("organizer", "desk organizer", use_cache=False)
        models = await svc.search_models("organizer")
        filtered = await svc.search_models("organizer", commercial_only=True)
        return m, models, filtered
    m, models, filtered = run(go())
    assert m["total_listings"] == 250 + 31 + 900 + 5000
    assert {s["source"] for s in m["sources"] if s["error"] is None} == {"allegro", "olx", "ebay", "etsy"}
    ebay = next(l for l in m["listings"] if l["source"] == "ebay")
    assert ebay["price_pln"] == pytest.approx(43.0)
    # Allegro jest domyślnym kanałem: mediana z Allegro
    assert svc.reference_price(m, "allegro")[0] == pytest.approx((39.99 + 59) / 2, abs=0.01)

    by_src = {s["source"]: s for s in models["sources"]}
    assert "searchPrints2" in by_src["printables"]["error"]
    hits = {h["source"]: h for h in models["hits"]}
    assert hits["cults3d"]["license"]["commercial_ok"] and hits["cults3d"]["license_total_pln"] == pytest.approx(12.9)
    assert hits["thingiverse"]["license_total_pln"] is None
    assert [h["source"] for h in filtered["hits"]] == ["cults3d"]
    assert models["matched_keyword"] is not None


def test_thingiverse_download_prefers_3mf():
    from trender.schemas import ModelHit

    async def go():
        async with client() as c:
            return await ThingiverseProvider(S).download(c, ModelHit(source="thingiverse", id="7", title="x"))
    name, data = run(go())
    assert name == "part.3mf" and data == b"3MFDATA"
