"""Profil kosztowy użytkownika: drukarki, filamenty, stawki, prowizje i wagi scoringu.

Wartości domyślne to szacunki dla Polski (2026) i drukarek Bambu Lab.
Wszystko można zmienić w zakładce "Ustawienia" aplikacji.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Printer(BaseModel):
    id: str
    name: str
    price_pln: float  # cena zakupu (z AMS, jeśli dotyczy)
    lifetime_hours: float  # zakładany czas pracy do pełnej amortyzacji
    avg_power_w: float  # średni pobór mocy podczas druku
    maintenance_per_hour_pln: float  # dysze, pasy, płyty PEI, smar...
    throughput_g_per_h: float  # średnia wydajność do szacowania czasu z samej wagi
    plate_overhead_min: float  # nagrzewanie, kalibracja, zmiana płyty (na jeden stół)
    purge_g_per_color_change: float = 0.0  # odpad AMS na jedną zmianę koloru


class Filament(BaseModel):
    id: str
    name: str
    price_per_kg_pln: float
    density_g_cm3: float


class MarketplaceFee(BaseModel):
    id: str
    name: str
    percent: float  # prowizja od ceny brutto (0.10 = 10%)
    fixed_pln: float = 0.0  # stała opłata za sprzedaż / wystawienie
    note: str = ""


class ScoreWeights(BaseModel):
    margin: float = 0.35
    demand: float = 0.30
    competition: float = 0.20
    season: float = 0.15


class Profile(BaseModel):
    printers: list[Printer]
    filaments: list[Filament]
    fees: list[MarketplaceFee]
    default_printer: str = "p1s"
    default_filament: str = "pla"
    default_channel: str = "allegro"
    energy_price_kwh_pln: float = 1.10
    labor_rate_h_pln: float = 40.0  # stawka za pracę ręczną (obróbka, pakowanie)
    packaging_pln: float = 2.50
    failure_rate: float = 0.05  # odsetek nieudanych wydruków
    waste_pct: float = 0.05  # podpory, brim, purge line
    vat_payer: bool = False
    vat_rate: float = 0.23
    target_margin: float = 0.35  # docelowa marża przy sugerowanej cenie
    target_profit_per_hour_pln: float = 25.0  # zysk/h drukarki uznawany za "bardzo dobry" (100 pkt)
    expected_units_per_model: int = 20  # na ile sztuk rozkładać koszt płatnej licencji / pliku
    weights: ScoreWeights = Field(default_factory=ScoreWeights)

    def printer(self, pid: str | None = None) -> Printer:
        pid = pid or self.default_printer
        return next((p for p in self.printers if p.id == pid), self.printers[0])

    def filament(self, fid: str | None = None) -> Filament:
        fid = fid or self.default_filament
        return next((f for f in self.filaments if f.id == fid), self.filaments[0])

    def fee(self, cid: str | None = None) -> MarketplaceFee:
        cid = cid or self.default_channel
        return next((f for f in self.fees if f.id == cid), self.fees[0])


def default_profile() -> Profile:
    return Profile(
        printers=[
            Printer(id="p1s", name="Bambu Lab P1S + AMS", price_pln=3900, lifetime_hours=6000,
                    avg_power_w=110, maintenance_per_hour_pln=0.25, throughput_g_per_h=35,
                    plate_overhead_min=6, purge_g_per_color_change=0.8),
            Printer(id="x1c", name="Bambu Lab X1C + AMS", price_pln=5900, lifetime_hours=6000,
                    avg_power_w=120, maintenance_per_hour_pln=0.30, throughput_g_per_h=38,
                    plate_overhead_min=7, purge_g_per_color_change=0.8),
            Printer(id="a1", name="Bambu Lab A1 + AMS lite", price_pln=2300, lifetime_hours=5000,
                    avg_power_w=95, maintenance_per_hour_pln=0.25, throughput_g_per_h=30,
                    plate_overhead_min=5, purge_g_per_color_change=1.0),
        ],
        filaments=[
            Filament(id="pla", name="PLA", price_per_kg_pln=70, density_g_cm3=1.24),
            Filament(id="pla_matte", name="PLA Matte", price_per_kg_pln=80, density_g_cm3=1.32),
            Filament(id="petg", name="PETG", price_per_kg_pln=75, density_g_cm3=1.27),
            Filament(id="abs", name="ABS", price_per_kg_pln=80, density_g_cm3=1.04),
            Filament(id="asa", name="ASA", price_per_kg_pln=95, density_g_cm3=1.07),
            Filament(id="tpu", name="TPU 95A", price_per_kg_pln=130, density_g_cm3=1.21),
            Filament(id="pla_cf", name="PLA-CF", price_per_kg_pln=140, density_g_cm3=1.30),
            Filament(id="silk", name="PLA Silk", price_per_kg_pln=85, density_g_cm3=1.24),
        ],
        fees=[
            MarketplaceFee(id="allegro", name="Allegro", percent=0.11, fixed_pln=0.0,
                           note="Prowizja zależy od kategorii (ok. 8-15%). Sprawdź cennik Allegro."),
            MarketplaceFee(id="olx", name="OLX", percent=0.0, fixed_pln=0.0,
                           note="Ogłoszenia prywatne zwykle bez prowizji; firmowe i promowanie płatne."),
            MarketplaceFee(id="etsy", name="Etsy", percent=0.095, fixed_pln=2.0,
                           note="6.5% transakcja + ok. 3% płatność + listing 0.20 USD i opłata stała płatności."),
            MarketplaceFee(id="ebay", name="eBay", percent=0.13, fixed_pln=1.5,
                           note="Final value fee ok. 11-13% + stała opłata za zamówienie."),
            MarketplaceFee(id="own", name="Własny sklep", percent=0.02, fixed_pln=0.0,
                           note="Tylko koszt bramki płatniczej."),
        ],
    )
