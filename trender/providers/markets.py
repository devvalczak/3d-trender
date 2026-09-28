"""Portale sprzedażowe: liczba ofert, ceny i (gdzie się da) sprzedaż konkurencji."""

from __future__ import annotations

import httpx

from ..config import Settings
from ..schemas import Listing, MarketResult
from .base import ProviderError, TokenCache, dig, raise_for, to_float, to_int


class AllegroProvider:
    """Allegro REST API, wyszukiwanie ofert: GET /offers/listing (token client_credentials).

    Uwaga: Allegro udostępnia /offers/listing tylko zweryfikowanym aplikacjom.
    Po rejestracji aplikacji złóż wniosek o dostęp w panelu deweloperskim Allegro.
    """

    name = "allegro"
    label = "Allegro"

    def __init__(self, s: Settings):
        self.client_id, self.secret = s.allegro_client_id, s.allegro_client_secret
        dom = "allegro.pl.allegrosandbox.pl" if s.allegro_sandbox else "allegro.pl"
        self.auth_url = f"https://{dom}/auth/oauth/token"
        self.api = f"https://api.{dom}"
        self.web = f"https://{dom}"
        self._token = TokenCache()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if tok := self._token.valid():
            return tok
        r = await client.post(self.auth_url, data={"grant_type": "client_credentials"},
                              auth=(self.client_id, self.secret))
        raise_for(r, "Allegro (token)")
        data = r.json()
        return self._token.set(data["access_token"], data.get("expires_in", 43200))

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 60) -> MarketResult:
        token = await self._get_token(client)
        r = await client.get(f"{self.api}/offers/listing",
                             params={"phrase": query, "limit": min(limit, 100)},
                             headers={"Authorization": f"Bearer {token}",
                                      "Accept": "application/vnd.allegro.public.v1+json"})
        raise_for(r, "Allegro")
        data = r.json()
        items = (dig(data, "items", "promoted", default=[]) or []) + (dig(data, "items", "regular", default=[]) or [])
        listings = []
        for it in items:
            price = to_float(dig(it, "sellingMode", "price", "amount"))
            if price is None:
                continue
            sold = dig(it, "sellingMode", "popularity")
            if sold is None:
                sold = dig(it, "popularity")
            listings.append(Listing(
                source=self.name, title=it.get("name", ""), price=price,
                currency=dig(it, "sellingMode", "price", "currency", default="PLN"),
                url=f"{self.web}/oferta/{it.get('id')}", seller=dig(it, "seller", "login"),
                sold=to_int(sold), image=dig(it, "images", 0, "url"),
            ))
        total = to_int(dig(data, "searchMeta", "totalCount")) or to_int(dig(data, "searchMeta", "availableCount"))
        return MarketResult(source=self.name, query=query, total=total, listings=listings)


class OlxProvider:
    """OLX.pl: publiczny endpoint wyszukiwania używany przez stronę (bez klucza, nieoficjalny)."""

    name = "olx"
    label = "OLX"
    URL = "https://www.olx.pl/api/v1/offers/"

    def __init__(self, s: Settings):
        self.enabled = s.olx_enabled

    @property
    def configured(self) -> bool:
        return self.enabled

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 40) -> MarketResult:
        r = await client.get(self.URL, params={"offset": 0, "limit": min(limit, 50), "query": query})
        raise_for(r, "OLX")
        data = r.json()
        listings = []
        for it in data.get("data", []):
            price_param = next((p for p in it.get("params", []) if p.get("key") == "price"), None)
            price = to_float(dig(price_param, "value", "value"))
            if price is None or price <= 0:
                continue
            listings.append(Listing(
                source=self.name, title=it.get("title", ""), price=price,
                currency=dig(price_param, "value", "currency", default="PLN"), url=it.get("url"),
                seller=dig(it, "user", "name"), image=dig(it, "photos", 0, "link", default="")
                .replace("{width}", "300").replace("{height}", "300") or None,
            ))
        total = to_int(dig(data, "metadata", "total_elements")) or to_int(dig(data, "metadata", "visible_total_count"))
        return MarketResult(source=self.name, query=query, total=total, listings=listings)


class EbayProvider:
    """eBay Browse API: GET /buy/browse/v1/item_summary/search (token aplikacji)."""

    name = "ebay"
    label = "eBay"
    TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    def __init__(self, s: Settings):
        self.client_id, self.secret, self.marketplace = s.ebay_client_id, s.ebay_client_secret, s.ebay_marketplace
        self._token = TokenCache()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if tok := self._token.valid():
            return tok
        r = await client.post(self.TOKEN_URL, auth=(self.client_id, self.secret),
                              data={"grant_type": "client_credentials",
                                    "scope": "https://api.ebay.com/oauth/api_scope"})
        raise_for(r, "eBay (token)")
        data = r.json()
        return self._token.set(data["access_token"], data.get("expires_in", 7200))

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 50) -> MarketResult:
        token = await self._get_token(client)
        r = await client.get(self.SEARCH_URL, params={"q": query, "limit": min(limit, 200)},
                             headers={"Authorization": f"Bearer {token}",
                                      "X-EBAY-C-MARKETPLACE-ID": self.marketplace})
        raise_for(r, "eBay")
        data = r.json()
        listings = []
        for it in data.get("itemSummaries", []) or []:
            price = to_float(dig(it, "price", "value"))
            if price is None:
                continue
            listings.append(Listing(
                source=self.name, title=it.get("title", ""), price=price,
                currency=dig(it, "price", "currency", default="EUR"), url=it.get("itemWebUrl"),
                seller=dig(it, "seller", "username"), image=dig(it, "image", "imageUrl"),
            ))
        return MarketResult(source=self.name, query=query, total=to_int(data.get("total")), listings=listings)


class EtsyProvider:
    """Etsy Open API v3: GET /v3/application/listings/active (nagłówek x-api-key)."""

    name = "etsy"
    label = "Etsy"
    URL = "https://openapi.etsy.com/v3/application/listings/active"

    def __init__(self, s: Settings):
        self.key, self.secret = s.etsy_api_key, s.etsy_shared_secret

    @property
    def configured(self) -> bool:
        return bool(self.key)

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 50) -> MarketResult:
        api_key = f"{self.key}:{self.secret}" if self.secret else self.key
        r = await client.get(self.URL, params={"keywords": query, "limit": min(limit, 100), "sort_on": "score"},
                             headers={"x-api-key": api_key})
        raise_for(r, "Etsy")
        data = r.json()
        listings = []
        for it in data.get("results", []) or []:
            amount, divisor = to_float(dig(it, "price", "amount")), to_float(dig(it, "price", "divisor")) or 100
            if amount is None:
                continue
            listings.append(Listing(
                source=self.name, title=it.get("title", ""), price=round(amount / divisor, 2),
                currency=dig(it, "price", "currency_code", default="USD"), url=it.get("url"),
                seller=str(it.get("shop_id")) if it.get("shop_id") else None,
                favorites=to_int(it.get("num_favorers")),
            ))
        return MarketResult(source=self.name, query=query, total=to_int(data.get("count")), listings=listings)


def market_providers(s: Settings) -> list:
    return [AllegroProvider(s), OlxProvider(s), EbayProvider(s), EtsyProvider(s)]


__all__ = ["AllegroProvider", "OlxProvider", "EbayProvider", "EtsyProvider", "market_providers", "ProviderError"]
