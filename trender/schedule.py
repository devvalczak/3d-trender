"""Optymalny harmonogram płyt w ciągu doby.

Model doby: przez `attended_hours` ktoś jest przy drukarce i może zmieniać płyty. Płyty
drukowane w tym czasie muszą się skończyć przed jego końcem (żeby zdjąć wydruk i puścić kolejny).
Opcjonalnie ostatnia płyta startuje przed wyjściem i drukuje się po godzinach ("nocna"), ale musi
skończyć się przed następnym dniem pracy. Sprawdzamy wszystkie kombinacje liczby sztuk na płycie
dziennej i nocnej i wybieramy najwyższy zysk na dobę.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel


class Schedule(BaseModel):
    day_units_per_plate: int
    day_plates: int
    night_units: int  # 0 = bez nocnej płyty
    units_per_day: int
    profit_per_day: float
    printer_hours_per_day: float
    day_plate_h: float
    night_plate_h: float
    label: str


def plate_hours(n: int, unit_h: float, plate_extra_h: float) -> float:
    return plate_extra_h + n * unit_h


def optimize(*, max_units: int, unit_h: float, plate_extra_h: float, unit_profit: Callable[[int], float],
             attended_hours: float, allow_night: bool, swap_min: float) -> tuple[Schedule | None, Schedule | None]:
    """Zwraca (optymalny, prosty). Prosty = tylko pełne płyty w godzinach pracy."""
    if max_units < 1 or unit_h <= 0:
        return None, None
    swap_h = swap_min / 60
    W = attended_hours
    profit = {n: unit_profit(n) for n in range(1, max_units + 1)}

    def build(nd: int, nn: int) -> Schedule | None:
        td = plate_hours(nd, unit_h, plate_extra_h)
        k = int(W // (td + swap_h)) if nd else 0
        start_night = k * (td + swap_h)
        tn = plate_hours(nn, unit_h, plate_extra_h) if nn else 0.0
        if nn:
            # nocna płyta startuje, gdy ktoś jest na miejscu, i musi się skończyć przed kolejnym dniem
            if start_night > W or start_night + tn > 24:
                return None
            if not allow_night and start_night + tn > W:
                return None
        if k == 0 and nn == 0:
            return None
        units = k * nd + nn
        p = k * nd * profit.get(nd, 0) + nn * profit.get(nn, 0)
        hours = k * td + tn
        if nn:
            label = f"{k}× płyta po {nd} szt. ({td:.1f} h) + płyta na noc {nn} szt. ({tn:.1f} h)" if k else \
                f"1 długa płyta {nn} szt. ({tn:.1f} h), startuje w godzinach pracy"
        else:
            label = f"{k}× płyta po {nd} szt. ({td:.1f} h)"
        return Schedule(day_units_per_plate=nd, day_plates=k, night_units=nn, units_per_day=units,
                        profit_per_day=round(p, 2), printer_hours_per_day=round(hours, 2), day_plate_h=round(td, 2),
                        night_plate_h=round(tn, 2), label=label)

    best = None
    for nd in range(0, max_units + 1):
        for nn in range(0, max_units + 1):
            sc = build(nd, nn)
            if sc and (best is None or sc.profit_per_day > best.profit_per_day
                       or (sc.profit_per_day == best.profit_per_day and sc.units_per_day < best.units_per_day)):
                best = sc
    simple = build(max_units, 0)
    if simple is None:
        # pełna płyta nie mieści się w godzinach pracy: największa, która się mieści
        for n in range(max_units, 0, -1):
            if (simple := build(n, 0)) is not None:
                break
    return best, simple
