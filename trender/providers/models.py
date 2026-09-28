"""Repozytoria modeli 3D: wyszukiwanie z licencją, ceną pliku i popularnością."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

import httpx

from ..config import Settings
from ..schemas import ModelHit
from .base import ProviderError, dig, raise_for, to_float, to_int


class ThingiverseProvider:
    name = "thingiverse"
    label = "Thingiverse"
    API = "https://api.thingiverse.com"

    def __init__(self, s: Settings):
        self.token = s.thingiverse_token

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 20) -> list[ModelHit]:
        headers = {"Authorization": f"Bearer {self.token}"}
        r = await client.get(f"{self.API}/search/{quote(query)}/",
                             params={"type": "things", "per_page": limit, "sort": "popular"}, headers=headers)
        raise_for(r, "Thingiverse")
        data = r.json()
        hits = data.get("hits", []) if isinstance(data, dict) else data
        hits = hits[:limit]

        # licencja jest tylko w szczegółach modelu
        async def detail(h):
            try:
                d = await client.get(f"{self.API}/things/{h['id']}", headers=headers)
                return d.json() if d.status_code == 200 else {}
            except httpx.HTTPError:
                return {}

        details = await asyncio.gather(*(detail(h) for h in hits[:12]))
        details += [{}] * (len(hits) - len(details))
        out = []
        for h, d in zip(hits, details):
            out.append(ModelHit(
                source=self.name, id=str(h.get("id")), title=h.get("name", ""), url=h.get("public_url"),
                image=h.get("thumbnail") or h.get("preview_image"), author=dig(h, "creator", "name"),
                likes=to_int(h.get("like_count")), downloads=to_int(d.get("download_count")),
                license_raw=d.get("license"), file_price=0.0,
            ))
        return out


    MAX_FILE = 60 * 1024 * 1024

    async def download(self, client: httpx.AsyncClient, hit: ModelHit) -> tuple[str, bytes] | None:
        """Pobiera plik do druku (preferuje .3mf, potem największy .stl) przez oficjalne API."""
        headers = {"Authorization": f"Bearer {self.token}"}
        r = await client.get(f"{self.API}/things/{hit.id}/files", headers=headers)
        raise_for(r, "Thingiverse (pliki)")
        files = [f for f in r.json() or [] if str(f.get("name", "")).lower().endswith((".3mf", ".stl"))]
        if not files:
            return None
        files.sort(key=lambda f: (not f["name"].lower().endswith(".3mf"), -(to_int(f.get("size")) or 0)))
        f = files[0]
        if (to_int(f.get("size")) or 0) > self.MAX_FILE:
            return None
        url = f.get("download_url") or f"{self.API}/files/{f.get('id')}/download"
        d = await client.get(url, headers=headers)
        raise_for(d, "Thingiverse (pobieranie)")
        return f["name"], d.content


class Cults3DProvider:
    """Cults3D GraphQL API (Basic Auth: nazwa użytkownika + klucz API)."""

    name = "cults3d"
    label = "Cults3D"
    URL = "https://cults3d.com/graphql"
    QUERY = """
    query Search($q: String!, $limit: Int) {
      creationsSearchBatch(query: $q, limit: $limit) {
        total
        results {
          identifier name url illustrationImageUrl likesCount downloadsCount
          price(currency: EUR) { cents }
          license { code name }
          creator { nick }
        }
      }
    }"""

    def __init__(self, s: Settings):
        self.user, self.key = s.cults3d_username, s.cults3d_api_key

    @property
    def configured(self) -> bool:
        return bool(self.user and self.key)

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 20) -> list[ModelHit]:
        r = await client.post(self.URL, json={"query": self.QUERY, "variables": {"q": query, "limit": limit}},
                              auth=(self.user, self.key))
        raise_for(r, "Cults3D")
        data = r.json()
        if data.get("errors"):
            raise ProviderError(f"Cults3D: {data['errors'][0].get('message')}")
        out = []
        for it in dig(data, "data", "creationsSearchBatch", "results", default=[]) or []:
            cents = to_float(dig(it, "price", "cents"))
            out.append(ModelHit(
                source=self.name, id=str(it.get("identifier") or it.get("url")), title=it.get("name", ""),
                url=it.get("url"), image=it.get("illustrationImageUrl"), author=dig(it, "creator", "nick"),
                likes=to_int(it.get("likesCount")), downloads=to_int(it.get("downloadsCount")),
                license_raw=dig(it, "license", "name"), license_code=dig(it, "license", "code"),
                file_price=cents / 100 if cents is not None else 0.0, file_currency="EUR",
            ))
        return out


class MyMiniFactoryProvider:
    name = "myminifactory"
    label = "MyMiniFactory"
    URL = "https://www.myminifactory.com/api/v2/search"

    def __init__(self, s: Settings):
        self.key = s.myminifactory_api_key

    @property
    def configured(self) -> bool:
        return bool(self.key)

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 20) -> list[ModelHit]:
        r = await client.get(self.URL, params={"q": query, "per_page": limit, "key": self.key})
        raise_for(r, "MyMiniFactory")
        out = []
        for it in r.json().get("items", []) or []:
            lic = it.get("license") or dig(it, "licenses", 0, "type") or dig(it, "licenses", 0)
            if isinstance(lic, dict):
                lic = lic.get("name") or lic.get("type")
            price = to_float(dig(it, "price", "value"))
            out.append(ModelHit(
                source=self.name, id=str(it.get("id")), title=it.get("name", ""), url=it.get("url"),
                image=dig(it, "images", 0, "thumbnail", "url"),
                author=dig(it, "designer", "name") or dig(it, "designer", "username"),
                likes=to_int(it.get("likes")), downloads=to_int(it.get("views")),
                license_raw=str(lic) if lic else None,
                file_price=price if price is not None else 0.0,
                file_currency=dig(it, "price", "currency", default="USD"),
            ))
        return out


class PrintablesProvider:
    """Printables (Prusa): nieoficjalne API GraphQL używane przez stronę, bez klucza."""

    name = "printables"
    label = "Printables"
    URL = "https://api.printables.com/graphql/"
    QUERY = """
    query SearchModels($query: String!, $limit: Int) {
      searchPrints2(query: $query, limit: $limit) {
        items {
          id name slug likesCount downloadCount
          license { name abbreviation }
          image { filePath }
          user { publicUsername }
        }
      }
    }"""

    def __init__(self, s: Settings):
        self.enabled = s.printables_enabled

    @property
    def configured(self) -> bool:
        return self.enabled

    async def search(self, client: httpx.AsyncClient, query: str, limit: int = 20) -> list[ModelHit]:
        r = await client.post(self.URL, json={"query": self.QUERY, "variables": {"query": query, "limit": limit}},
                              headers={"Content-Type": "application/json"})
        raise_for(r, "Printables")
        data = r.json()
        if data.get("errors"):
            raise ProviderError(f"Printables: {data['errors'][0].get('message')} (API nieoficjalne, mogło się zmienić)")
        out = []
        for it in dig(data, "data", "searchPrints2", "items", default=[]) or []:
            fp = dig(it, "image", "filePath")
            out.append(ModelHit(
                source=self.name, id=str(it.get("id")), title=it.get("name", ""),
                url=f"https://www.printables.com/model/{it.get('id')}-{it.get('slug', '')}",
                image=f"https://media.printables.com/{fp}" if fp else None,
                author=dig(it, "user", "publicUsername"), likes=to_int(it.get("likesCount")),
                downloads=to_int(it.get("downloadCount")),
                license_raw=dig(it, "license", "name") or dig(it, "license", "abbreviation"), file_price=0.0,
            ))
        return out


def model_providers(s: Settings) -> list:
    return [ThingiverseProvider(s), Cults3DProvider(s), MyMiniFactoryProvider(s), PrintablesProvider(s)]
