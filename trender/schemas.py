"""Wspólne struktury danych przekazywane między dostawcami, logiką i API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CommercialStatus = Literal["allowed", "attribution", "no_derivatives", "paid", "non_commercial", "unknown"]


class Listing(BaseModel):
    source: str
    title: str
    price: float
    currency: str = "PLN"
    price_pln: float | None = None
    url: str | None = None
    seller: str | None = None
    sold: int | None = None  # sprzedane sztuki (np. popularność Allegro z ostatnich 30 dni)
    favorites: int | None = None  # np. num_favorers na Etsy
    image: str | None = None
    demo: bool = False


class MarketResult(BaseModel):
    source: str
    query: str
    total: int | None = None  # liczba wszystkich ofert dla frazy
    listings: list[Listing] = Field(default_factory=list)
    error: str | None = None
    demo: bool = False


class TrendPoint(BaseModel):
    date: str
    value: float


class TrendSeries(BaseModel):
    keyword: str
    source: str
    points: list[TrendPoint] = Field(default_factory=list)
    momentum: float | None = None  # zmiana średniej z ostatnich 4 tygodni vs 12 wcześniejszych (0.25 = +25%)
    level: float | None = None  # średnia z ostatnich 4 tygodni, 0-100 (skala Google Trends danej frazy)
    error: str | None = None
    demo: bool = False


class LicenseInfo(BaseModel):
    status: CommercialStatus
    commercial_ok: bool
    label: str
    note: str = ""


class ModelHit(BaseModel):
    source: str
    id: str
    title: str
    url: str | None = None
    image: str | None = None
    author: str | None = None
    likes: int | None = None
    downloads: int | None = None
    license_raw: str | None = None
    license_code: str | None = None
    license: LicenseInfo | None = None
    file_price: float | None = None  # cena pliku w walucie serwisu (0 = darmowy)
    file_currency: str = "EUR"
    file_price_pln: float | None = None
    commercial_license_cost_pln: float | None = None  # znany koszt licencji komercyjnej
    est_weight_g: float | None = None
    est_time_h: float | None = None
    size_mm: list[float] | None = None  # [x, y, z] jeśli znane (z pliku lub serwisu)
    colors: int | None = None
    color_changes: int | None = None  # zmiany koloru na płytę
    size_source: str | None = None
    demo: bool = False
