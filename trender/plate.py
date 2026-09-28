"""Układanie identycznych obiektów na stole drukarki (obrys prostokątny + obrót 0°/90°).

Szukamy najlepszego z układów: czysta siatka w jednej orientacji albo stół podzielony na dwa
bloki (każdy z inną orientacją). Pozycje kolidujące ze strefami wykluczenia są usuwane.
Obrys prostokątny lekko zaniża wynik dla okrągłych kształtów: to świadomie ostrożny szacunek.
"""

from __future__ import annotations

from pydantic import BaseModel


class PlateLayout(BaseModel):
    units: int
    bed: list[float]  # [x, y]
    footprint: list[float]  # [x, y] obiektu w orientacji bazowej
    spacing: float
    margin: float
    positions: list[list[float]]  # [x, y, w, h] od lewego przedniego rogu
    exclude: list[list[float]] = []
    fits: bool = True
    note: str = ""


def _grid(x0: float, y0: float, W: float, H: float, w: float, h: float, s: float) -> list[list[float]]:
    if w > W or h > H:
        return []
    nx = int((W + s) // (w + s))
    ny = int((H + s) // (h + s))
    return [[x0 + i * (w + s), y0 + j * (h + s), w, h] for i in range(nx) for j in range(ny)]


def _overlaps(p: list[float], r: list[float], s: float) -> bool:
    x, y, w, h = p
    return not (x + w + s / 2 <= r[0] or x - s / 2 >= r[2] or y + h + s / 2 <= r[1] or y - s / 2 >= r[3])


def _filter(pos: list[list[float]], exclude: list[list[float]], s: float) -> list[list[float]]:
    return [p for p in pos if not any(_overlaps(p, r, s) for r in exclude)]


def layout(obj_x: float, obj_y: float, bed_x: float = 256, bed_y: float = 256, spacing: float = 5,
           margin: float = 5, exclude: list[list[float]] | None = None, max_units: int | None = None) -> PlateLayout:
    exclude = exclude or []
    s = spacing
    X0 = Y0 = margin
    W, H = bed_x - 2 * margin, bed_y - 2 * margin
    candidates: list[list[list[float]]] = []
    for w, h in ((obj_x, obj_y), (obj_y, obj_x)):
        candidates.append(_grid(X0, Y0, W, H, w, h, s))
        # podział pionowy: lewy blok w orientacji (w,h), prawy w obróconej
        nx_max = int((W + s) // (w + s)) if w <= W else 0
        for nx in range(1, nx_max):
            used = nx * (w + s)
            left = _grid(X0, Y0, used - s, H, w, h, s)
            right = _grid(X0 + used, Y0, W - used, H, h, w, s)
            candidates.append(left + right)
        # podział poziomy: dolny blok (w,h), górny obrócony
        ny_max = int((H + s) // (h + s)) if h <= H else 0
        for ny in range(1, ny_max):
            used = ny * (h + s)
            bottom = _grid(X0, Y0, W, used - s, w, h, s)
            top = _grid(X0, Y0 + used, W, H - used, h, w, s)
            candidates.append(bottom + top)

    best = max((_filter(c, exclude, s) for c in candidates), key=len, default=[])
    if max_units is not None:
        best = best[:max_units]
    fits = bool(best)
    return PlateLayout(
        units=len(best), bed=[bed_x, bed_y], footprint=[obj_x, obj_y], spacing=spacing, margin=margin,
        positions=[[round(v, 1) for v in p] for p in best], exclude=exclude, fits=fits,
        note="" if fits else "Obiekt nie mieści się na stole: podziel model albo wybierz większą drukarkę.",
    )
