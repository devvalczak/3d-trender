"""Kalkulator kosztu wydruku, ceny sugerowanej i zysku."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .profile import Profile


class CostInput(BaseModel):
    weight_g: float = Field(gt=0)
    print_time_h: float = Field(gt=0, description="Czas druku jednej sztuki (bez nagrzewania)")
    printer_id: str | None = None
    filament_id: str | None = None
    units_per_plate: int = Field(1, ge=1, description="Ile sztuk mieści się na jednym stole")
    color_changes: int = Field(0, ge=0, description="Zmiany koloru AMS na sztukę")
    post_processing_min: float = Field(0, ge=0)
    license_cost_pln: float = Field(0, ge=0, description="Koszt pliku/licencji komercyjnej (całość)")
    channel: str | None = None
    sale_price_pln: float | None = Field(None, ge=0, description="Cena sprzedaży do policzenia zysku")


class CostBreakdown(BaseModel):
    filament_g: float
    material: float
    energy: float
    depreciation: float
    maintenance: float
    labor: float
    packaging: float
    license: float
    failure_allowance: float
    total: float
    machine_time_h: float  # czas drukarki na sztukę, z narzutem stołu
    printer: str
    filament: str


class PriceResult(BaseModel):
    channel: str
    price: float
    fees: float
    vat: float
    profit: float
    margin: float  # zysk / cena
    profit_per_hour: float


class CostResult(BaseModel):
    cost: CostBreakdown
    suggested: PriceResult
    at_price: PriceResult | None = None


def _r(x: float) -> float:
    return round(x, 2)


def compute_cost(inp: CostInput, profile: Profile) -> CostBreakdown:
    printer = profile.printer(inp.printer_id)
    fil = profile.filament(inp.filament_id)

    purge = inp.color_changes * printer.purge_g_per_color_change
    filament_g = inp.weight_g * (1 + profile.waste_pct) + purge
    material = filament_g / 1000 * fil.price_per_kg_pln

    machine_h = inp.print_time_h + printer.plate_overhead_min / 60 / inp.units_per_plate
    energy = printer.avg_power_w / 1000 * machine_h * profile.energy_price_kwh_pln
    depreciation = printer.price_pln / printer.lifetime_hours * machine_h
    maintenance = printer.maintenance_per_hour_pln * machine_h
    labor = inp.post_processing_min / 60 * profile.labor_rate_h_pln
    license_unit = inp.license_cost_pln / max(profile.expected_units_per_model, 1)

    production = material + energy + depreciation + maintenance
    # nieudane wydruki: tracimy materiał i czas maszyny, nie pracę ręczną
    failure = production * profile.failure_rate / (1 - profile.failure_rate)
    total = production + failure + labor + profile.packaging_pln + license_unit

    return CostBreakdown(
        filament_g=_r(filament_g), material=_r(material), energy=_r(energy),
        depreciation=_r(depreciation), maintenance=_r(maintenance), labor=_r(labor),
        packaging=_r(profile.packaging_pln), license=_r(license_unit), failure_allowance=_r(failure),
        total=_r(total), machine_time_h=round(machine_h, 3), printer=printer.name, filament=fil.name,
    )


def price_result(price: float, cost_total: float, machine_h: float, profile: Profile,
                 channel: str | None = None) -> PriceResult:
    fee = profile.fee(channel)
    fees = price * fee.percent + fee.fixed_pln if price > 0 else 0.0
    vat = price * profile.vat_rate / (1 + profile.vat_rate) if profile.vat_payer else 0.0
    profit = price - fees - vat - cost_total
    return PriceResult(
        channel=fee.name, price=_r(price), fees=_r(fees), vat=_r(vat), profit=_r(profit),
        margin=round(profit / price, 4) if price > 0 else 0.0,
        profit_per_hour=_r(profit / machine_h) if machine_h > 0 else 0.0,
    )


def suggested_price(cost_total: float, profile: Profile, channel: str | None = None) -> float:
    """Cena, przy której zysk = target_margin * cena po prowizjach i VAT."""
    fee = profile.fee(channel)
    vat_share = profile.vat_rate / (1 + profile.vat_rate) if profile.vat_payer else 0.0
    denom = 1 - fee.percent - vat_share - profile.target_margin
    if denom <= 0.05:
        denom = 0.05
    return (cost_total + fee.fixed_pln) / denom


def calculate(inp: CostInput, profile: Profile) -> CostResult:
    cost = compute_cost(inp, profile)
    sp = suggested_price(cost.total, profile, inp.channel)
    # zaokrąglenie "sklepowe" w górę do x,99
    sp = max(int(sp) + 0.99, 0.99)
    suggested = price_result(sp, cost.total, cost.machine_time_h, profile, inp.channel)
    at_price = None
    if inp.sale_price_pln:
        at_price = price_result(inp.sale_price_pln, cost.total, cost.machine_time_h, profile, inp.channel)
    return CostResult(cost=cost, suggested=suggested, at_price=at_price)
