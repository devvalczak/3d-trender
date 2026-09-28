"""Przeliczanie walut na PLN po średnim kursie NBP (tabela A)."""

from __future__ import annotations

import time

import httpx

from .providers.base import make_client

NBP_URL = "https://api.nbp.pl/api/exchangerates/tables/a/?format=json"
# awaryjne kursy, gdy NBP jest niedostępne
FALLBACK = {"PLN": 1.0, "EUR": 4.25, "USD": 3.70, "GBP": 4.95, "CZK": 0.17, "CHF": 4.55, "SEK": 0.39}


class Rates:
    def __init__(self):
        self.rates: dict[str, float] = dict(FALLBACK)
        self.fetched = 0.0
        self.live = False

    async def refresh(self, client: httpx.AsyncClient | None = None) -> None:
        if time.time() - self.fetched < 12 * 3600:
            return
        self.fetched = time.time()
        own = client is None
        client = client or make_client()
        try:
            r = await client.get(NBP_URL)
            r.raise_for_status()
            for item in r.json()[0]["rates"]:
                self.rates[item["code"]] = float(item["mid"])
            self.live = True
        except Exception:  # noqa: BLE001 - brak NBP nie może blokować aplikacji
            self.live = False
            self.fetched = time.time() - 12 * 3600 + 600  # ponów za 10 minut
        finally:
            if own:
                await client.aclose()

    def to_pln(self, amount: float | None, currency: str | None) -> float | None:
        if amount is None:
            return None
        rate = self.rates.get((currency or "PLN").upper())
        return round(amount * rate, 2) if rate else None


rates = Rates()
