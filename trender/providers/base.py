"""Wspólne elementy dostawców danych."""

from __future__ import annotations

import time
from typing import Any

import httpx

USER_AGENT = "3d-trender/0.1 (+https://github.com/devvalczak/3d-trender)"


class ProviderError(Exception):
    pass


def make_client(**kw) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers={"User-Agent": USER_AGENT},
                             follow_redirects=True, **kw)


class TokenCache:
    """Token OAuth2 client_credentials trzymany w pamięci do wygaśnięcia."""

    def __init__(self):
        self.token: str | None = None
        self.expires = 0.0

    def valid(self) -> str | None:
        return self.token if self.token and time.time() < self.expires - 60 else None

    def set(self, token: str, expires_in: float) -> str:
        self.token, self.expires = token, time.time() + float(expires_in or 3600)
        return token


def dig(obj: Any, *path, default=None):
    """Bezpieczne sięganie w zagnieżdżony JSON: dig(d, "a", 0, "b")."""
    for p in path:
        try:
            obj = obj[p]
        except (KeyError, IndexError, TypeError):
            return default
    return obj if obj is not None else default


def to_float(x: Any) -> float | None:
    try:
        return float(str(x).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def to_int(x: Any) -> int | None:
    f = to_float(x)
    return int(f) if f is not None else None


def raise_for(resp: httpx.Response, source: str) -> None:
    if resp.status_code >= 400:
        body = resp.text[:300].replace("\n", " ")
        hint = ""
        if resp.status_code in (401, 403):
            hint = " (sprawdź klucze API / uprawnienia aplikacji)"
        elif resp.status_code == 429:
            hint = " (limit zapytań: spróbuj później)"
        raise ProviderError(f"{source}: HTTP {resp.status_code}{hint}: {body}")
