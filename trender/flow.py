"""Asystent: jeden lejek od trendów do planu produkcji.

Etapy:
 1. Trendy   - ocena obserwowanych fraz (popyt, konkurencja, sezon, marża), top N przechodzi dalej.
 2. Modele   - ile modeli jest dostępnych, ile nadaje się do sprzedaży, wybór najlepszych kandydatów,
               pobranie pliku (gdzie API pozwala) i odczyt wymiarów / wagi / czasu.
 3. Stół     - ile sztuk mieści się na płycie przy zadanym odstępie.
 4. Zysk     - warianty AMS vs jednokolorowy + malowanie, optymalny harmonogram doby, zysk/dzień.
Na końcu: plan produkcji na N dni, szkic aukcji, porównanie z poprzednim przebiegiem.

Punkty kontrolne: użytkownik może wykluczyć pozycję, wybrać innego kandydata, poprawić
wymiary/wagę/czas/kolory/cenę albo wgrać plik. Wtedy przeliczamy tylko etapy 3-4 (bez API).
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid

from pydantic import BaseModel

from .costing import CostInput, calculate
from .fileparse import analyze_file
from .plate import layout
from .profile import FlowDefaults, Profile
from .schedule import optimize
from .scoring import clamp, pln, tier
from .services import Services


class FlowParams(FlowDefaults):
    printer_id: str | None = None
    keyword_ids: list[int] | None = None  # None = wszystkie aktywne frazy
    refresh: bool = False  # pomiń cache API
    download_files: bool = True


class ItemOverride(BaseModel):
    excluded: bool | None = None
    selected: int | None = None  # indeks kandydata; -1 = bez modelu (parametry z frazy)
    size_x: float | None = None
    size_y: float | None = None
    size_z: float | None = None
    unit_weight_g: float | None = None
    unit_time_h: float | None = None
    colors: int | None = None
    color_changes: int | None = None
    sale_price_pln: float | None = None
    filament: str | None = None
    post_min: float | None = None


STAGES = ["Trendy", "Modele", "Stół", "Zysk"]


# ---------------------------------------------------------------------------- obliczenia (czyste)

def item_spec(item: dict, kw: dict, profile: Profile) -> dict:
    """Parametry wydruku z priorytetem: korekta użytkownika > plik/serwis modelu > fraza z katalogu."""
    ov = item.get("overrides", {})
    cands = item["models"]["candidates"]
    sel = ov.get("selected", item["models"].get("selected", 0))
    cand = cands[sel] if cands and sel is not None and 0 <= sel < len(cands) else None
    f = cand.get("file") if cand else None

    def pick(key_ov, *sources):
        if ov.get(key_ov) is not None:
            return ov[key_ov], "ręcznie"
        for val, label in sources:
            if val is not None:
                return val, label
        return None, None

    size, size_src = pick("_size", ((f or {}).get("bbox_mm"), "plik modelu"),
                          ((cand or {}).get("size_mm"), (cand or {}).get("size_source") or "serwis"),
                          ([kw.get("size_x"), kw.get("size_y"), kw.get("size_z")] if kw.get("size_x") else None,
                           "typowe dla frazy"))
    size = list(size or [60, 60, 40])
    for i, k in enumerate(("size_x", "size_y", "size_z")):
        if ov.get(k) is not None:
            size[i], size_src = ov[k], "ręcznie"
    weight, w_src = pick("unit_weight_g", ((f or {}).get("unit_weight_g"), "plik modelu"),
                         ((cand or {}).get("weight_g") if cand and cand.get("weight_source") == "model" else None, "serwis"),
                         (kw.get("weight_g"), "typowe dla frazy"))
    hours, _ = pick("unit_time_h", ((f or {}).get("unit_time_h"), "plik modelu"),
                    ((cand or {}).get("time_h") if cand and cand.get("weight_source") == "model" else None, "serwis"),
                    (kw.get("time_h"), "typowe dla frazy"))
    colors, _ = pick("colors", ((cand or {}).get("colors"), "serwis"), (kw.get("colors") or 1, "fraza"))
    colors = max(int(colors or 1), 1)
    changes, _ = pick("color_changes", ((f or {}).get("color_changes"), "plik"),
                      ((cand or {}).get("color_changes"), "serwis"), (kw.get("color_changes"), "fraza"))
    changes = int(changes or 0)
    if colors > 1 and changes == 0:
        changes = colors - 1  # minimum: kolory warstwami (np. napis na podstawie)
    if colors == 1:
        changes = 0
    market_price = item["opportunity"]["market"].get("reference_price")
    price, p_src = pick("sale_price_pln", (market_price, "mediana rynku"))
    return {
        "candidate": sel if cand else None, "size": [round(float(v), 1) for v in size], "size_source": size_src,
        "unit_weight_g": round(float(weight or 50), 2), "unit_time_h": round(float(hours or 2), 3), "weight_source": w_src,
        "colors": colors, "color_changes": changes,
        "filament": ov.get("filament") or kw.get("filament") or profile.default_filament,
        "post_min": ov.get("post_min") if ov.get("post_min") is not None else (kw.get("post_min") or 0),
        "license_total": (cand or {}).get("license_total_pln") or 0.0,
        "price": price, "price_source": p_src,
    }


def compute_item(item: dict, kw: dict, params: FlowParams, profile: Profile) -> dict:
    spec = item_spec(item, kw, profile)
    printer = profile.printer(params.printer_id)
    warnings: list[str] = []
    plate = layout(spec["size"][0], spec["size"][1], printer.bed_x_mm, printer.bed_y_mm, params.spacing_mm,
                   params.margin_mm, printer.bed_exclude)
    if spec["size"][2] > 250:
        warnings.append(f"Wysokość {spec['size'][2]:.0f} mm przekracza wysokość roboczą drukarki.")
    if not plate.fits:
        warnings.append(plate.note)

    price = spec["price"]
    if price is None:
        warnings.append("Brak cen konkurencji: liczę przy cenie minimalnej (docelowa marża).")

    modes = [("single", "Jednokolorowy", 0, spec["post_min"])]
    if spec["colors"] > 1:
        modes = [
            ("ams", f"AMS {spec['colors']} kolory", spec["color_changes"], spec["post_min"]),
            ("paint", "1 kolor + malowanie", 0, spec["post_min"] + params.paint_min_per_color * (spec["colors"] - 1)),
        ]

    variants = []
    for vid, label, changes, post in modes:
        def calc(n: int, _c=changes, _p=post):
            inp = CostInput(weight_g=spec["unit_weight_g"], print_time_h=spec["unit_time_h"], printer_id=printer.id,
                            filament_id=spec["filament"], units_per_plate=n, color_changes=_c, post_processing_min=_p,
                            license_cost_pln=spec["license_total"], channel=profile.default_channel)
            base = calculate(inp, profile)
            sale = price if price is not None else base.suggested.price
            return calculate(inp.model_copy(update={"sale_price_pln": sale}), profile)

        if not plate.fits:
            variants.append({"id": vid, "label": label, "fits": False})
            continue
        cache: dict[int, object] = {}

        def unit_profit(n: int) -> float:
            if n not in cache:
                cache[n] = calc(n)
            return cache[n].at_price.profit

        extra_h = printer.plate_overhead_min / 60 + changes * printer.color_change_s / 3600
        best, simple = optimize(max_units=plate.units, unit_h=spec["unit_time_h"], plate_extra_h=extra_h,
                                unit_profit=unit_profit, attended_hours=params.attended_hours,
                                allow_night=params.allow_night, swap_min=params.swap_min)
        full = calc(plate.units)
        variants.append({
            "id": vid, "label": label, "fits": True, "color_changes": changes, "post_min": post,
            "cost": full.cost.model_dump(), "at_price": full.at_price.model_dump(), "min_price": full.suggested.price,
            "plate_h": round(extra_h + plate.units * spec["unit_time_h"], 2),
            "plate_filament_g": round(full.cost.filament_g * plate.units, 1),
            "profit_plate": round(full.at_price.profit * plate.units, 2),
            "schedule": best.model_dump() if best else None, "simple": simple.model_dump() if simple else None,
        })

    ok = [v for v in variants if v.get("schedule")]
    best_v = max(ok, key=lambda v: v["schedule"]["profit_per_day"]) if ok else None
    profit_day = best_v["schedule"]["profit_per_day"] if best_v else 0.0
    units_day = best_v["schedule"]["units_per_day"] if best_v else 0
    if best_v and best_v["at_price"]["profit"] <= 0:
        warnings.append("Przy tej cenie sprzedaż jest nieopłacalna.")
    if best_v:
        sch = best_v["schedule"]
        biggest = max(sch["day_units_per_plate"] if sch["day_plates"] else 0, sch["night_units"])
        plate_g = best_v["cost"]["filament_g"] * biggest
        if plate_g > 950:
            warnings.append(f"Największa płyta w harmonogramie zużywa {plate_g:.0f} g: sprawdź, czy wystarczy filamentu na szpuli.")

    # czy rynek wchłonie produkcję: sprzedaż top ofert z 30 dni jako przybliżenie popytu
    sold = item["opportunity"]["market"].get("stats", {}).get("sold_sum")
    cap_day = round(sold / 30 * params.market_share, 1) if sold else None
    if cap_day is not None and units_day > cap_day * 1.5:
        warnings.append(f"Produkujesz {units_day} szt./dzień, a realny zbyt to ok. {cap_day} szt./dzień "
                        f"({int(params.market_share * 100)}% sprzedaży konkurencji). Rozważ mniejsze serie.")
    if item["opportunity"]["ip"]["level"] == "high":
        warnings.append(item["opportunity"]["ip"]["note"])
    cand = item["models"]["candidates"][spec["candidate"]] if spec["candidate"] is not None else None
    if cand is None and item["models"]["candidates"] == [] and params.commercial_only:
        warnings.append("Nie znaleziono modelu z licencją komercyjną: zaprojektuj własny lub kup licencję.")

    # zysk ze sztuk, które realnie da się sprzedać (reszta czasu drukarki idzie na inne produkty)
    unit_profit_best = profit_day / units_day if units_day else 0.0
    sellable_units = min(units_day, cap_day) if cap_day is not None else units_day
    sellable_profit_day = round(unit_profit_best * sellable_units, 2)
    target_day = profile.target_profit_per_hour_pln * params.attended_hours
    profit_score = clamp(sellable_profit_day / target_day) * 100 if target_day > 0 else 0
    final = round(0.5 * item["opportunity"]["score"] + 0.5 * profit_score, 1)
    if item["opportunity"]["ip"]["level"] == "high":
        final = round(final * 0.3, 1)

    return {
        **item, "spec": spec, "plate": plate.model_dump(), "variants": variants,
        "best_variant": best_v["id"] if best_v else None, "profit_day": profit_day, "units_day": units_day,
        "sellable_profit_day": sellable_profit_day,
        "cap_day": cap_day, "final_score": final, "tier": tier(final), "warnings": warnings,
        "listing": listing_draft(item, spec, best_v, cand, profile),
    }


def listing_draft(item: dict, spec: dict, variant: dict | None, cand: dict | None, profile: Profile) -> dict:
    kw = item["keyword"]
    fil = profile.filament(spec["filament"]).name
    x, y, z = spec["size"]
    title = f"{kw[:1].upper()}{kw[1:]} - druk 3D {fil}, {x / 10:.0f}x{y / 10:.0f} cm"
    if item.get("category") == "Personalizowane":
        title = f"{kw[:1].upper()}{kw[1:]} personalizowany - druk 3D {fil}"
    title = title[:75]  # limit Allegro
    market = item["opportunity"]["market"]
    min_price = variant["min_price"] if variant else None
    median = market.get("reference_price")
    price = None
    if median:
        price = max(math.floor(median) - 0.01, min_price or 0)
    elif min_price:
        price = min_price
    lines = [
        f"Wymiary: ok. {x:.0f} x {y:.0f} x {z:.0f} mm",
        f"Materiał: {fil}" + (f", {spec['colors']} kolory" if spec["colors"] > 1 else ""),
        "Wydruk 3D wykonany na zamówienie, każda sztuka sprawdzana przed wysyłką.",
    ]
    notes = []
    if cand:
        lic = (cand.get("license") or {}).get("status")
        if lic in ("attribution", "no_derivatives"):
            lines.append(f"Projekt: „{cand['title']}” autorstwa {cand.get('author') or 'autora'} "
                         f"({cand.get('license_raw') or 'licencja CC'}).")
            notes.append("Licencja wymaga podania autora: zostaw linię 'Projekt:' w opisie.")
        if lic == "no_derivatives":
            notes.append("Licencja ND: nie modyfikuj modelu.")
        if lic == "paid":
            notes.append("Przed wystawieniem kup licencję komercyjną u autora.")
    if item["opportunity"]["ip"]["level"] != "none":
        notes.append(item["opportunity"]["ip"]["note"])
    return {"title": title, "price": round(price, 2) if price else None, "description": "\n".join(lines),
            "tags": [t for t in (kw, item.get("keyword_en")) if t], "notes": notes}


def build_plan(items: list[dict], params: FlowParams, profile: Profile) -> dict:
    """Rozdziela dni pracy drukarki między pozycje od najwyższego zysku/dzień.

    Produkt z limitem zbytu dostaje tylko tyle czasu, ile trzeba na sprzedawalną ilość
    (minimum jedna płyta), a zwolniony czas przechodzi na kolejne pozycje.
    """
    days_left = float(params.plan_days)
    rows = []
    for it in sorted((i for i in items if not i.get("excluded") and i.get("profit_day", 0) > 0),
                     key=lambda i: i["profit_day"], reverse=True):
        if days_left < 0.05:
            break
        v = next(v for v in it["variants"] if v["id"] == it["best_variant"])
        per_day = it["units_day"]
        sch = v["schedule"]
        one_plate = sch["day_units_per_plate"] if sch["day_plates"] else sch["night_units"]
        units = int(per_day * days_left)
        if it.get("cap_day") is not None:
            units = min(units, max(int(it["cap_day"] * params.plan_days), one_plate))
        if units <= 0:
            continue
        days = min(days_left, units / per_day)
        unit_profit = it["profit_day"] / per_day
        rows.append({
            "keyword": it["keyword"], "variant": v["label"], "days": round(days, 1), "units": units,
            "schedule": sch["label"], "profit": round(unit_profit * units, 2),
            "filament": profile.filament(it["spec"]["filament"]).name,
            "filament_g": round(v["cost"]["filament_g"] * units, 0),
            "limited": it.get("cap_day") is not None and units < int(per_day * (days_left)),
        })
        days_left -= days
    by_fil: dict[str, float] = {}
    for r in rows:
        by_fil[r["filament"]] = by_fil.get(r["filament"], 0) + r["filament_g"]
    return {"days": params.plan_days, "rows": rows, "profit": round(sum(r["profit"] for r in rows), 2),
            "units": sum(r["units"] for r in rows), "idle_days": round(max(days_left, 0), 1),
            "filament_kg": {k: round(v / 1000, 2) for k, v in by_fil.items()}}


# ---------------------------------------------------------------------------- przebieg

class FlowRunner:
    def __init__(self, svc: Services):
        self.svc = svc
        self.runs: dict[str, dict] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, run_id: str) -> dict | None:
        if run_id in self.runs:
            return self.runs[run_id]
        saved = self.svc.store.get_flow_run(run_id)
        if saved:
            saved.update(status="done", stage=len(STAGES), progress="")
            self.runs[run_id] = saved
        return saved

    def start(self, params: FlowParams) -> dict:
        run_id = uuid.uuid4().hex[:12]
        state = {"id": run_id, "created_at": time.time(), "status": "running", "stage": 0, "progress": "",
                 "params": params.model_dump(), "items": [], "others": [], "plan": None, "compare": None, "error": None}
        self.runs[run_id] = state
        self._locks[run_id] = asyncio.Lock()
        asyncio.create_task(self._run(run_id, params))
        return state

    async def _run(self, run_id: str, params: FlowParams) -> None:
        st = self.runs[run_id]
        try:
            async with self._locks[run_id]:
                await self._stage_trends(st, params)
                await self._stage_models(st, params)
                st["stage"], st["progress"] = 2, "Układanie na stole i liczenie zysku..."
                self._recompute(st, params)
                st["status"], st["stage"], st["progress"] = "done", len(STAGES), ""
                self._compare(st)
                self._save(st)
        except Exception as e:  # noqa: BLE001 - błąd pokazujemy w interfejsie
            st["status"], st["error"] = "error", str(e)

    async def _stage_trends(self, st: dict, params: FlowParams) -> None:
        st["stage"] = 0
        kws = [k for k in self.svc.store.list_keywords(active_only=True)
               if not params.keyword_ids or k["id"] in params.keyword_ids]
        results = []
        sem = asyncio.Semaphore(3)

        async def one(kw):
            async with sem:
                try:
                    results.append(await self.svc.evaluate_keyword(kw, use_cache=not params.refresh))
                except Exception as e:  # noqa: BLE001
                    st.setdefault("errors", []).append(f"{kw['keyword']}: {e}")
                st["progress"] = f"Analiza trendów: {len(results)}/{len(kws)}"

        await asyncio.gather(*(one(k) for k in kws))
        results.sort(key=lambda o: o["score"], reverse=True)
        top = [o for o in results if o["ip"]["level"] != "high"][:params.top_n]
        st["items"] = [self._new_item(o) for o in top]
        st["others"] = [{"keyword_id": o["keyword_id"], "keyword": o["keyword"], "score": o["score"],
                         "tier": o["tier"], "ip": o["ip"]["level"]} for o in results if o not in top]

    @staticmethod
    def _new_item(o: dict) -> dict:
        return {"keyword_id": o["keyword_id"], "keyword": o["keyword"], "keyword_en": o.get("keyword_en"),
                "category": o.get("category"), "excluded": False, "overrides": {},
                "opportunity": {k: o[k] for k in ("score", "tier", "subscores", "reasons", "trend", "season",
                                                  "market", "ip", "demo")},
                "models": {"total": 0, "commercial": 0, "candidates": [], "selected": 0, "sources": []}}

    async def _stage_models(self, st: dict, params: FlowParams, items: list[dict] | None = None) -> None:
        st["stage"] = 1
        items = items if items is not None else st["items"]
        sem = asyncio.Semaphore(3)
        done = 0

        async def one(it):
            nonlocal done
            async with sem:
                await self._models_for(it, params)
                done += 1
                st["progress"] = f"Szukanie modeli: {done}/{len(items)}"

        await asyncio.gather(*(one(i) for i in items))

    async def _models_for(self, it: dict, params: FlowParams) -> None:
        q = it["keyword"]
        res = await self.svc.search_models(q, with_market=False)
        hits = res["hits"]
        usable = [h for h in hits if h["license_total_pln"] is not None
                  and (params.max_license_cost_pln is None or h["license_total_pln"] <= params.max_license_cost_pln)]
        pool = usable if params.commercial_only else hits
        cands = pool[:params.models_per_item]
        it["models"] = {"total": len(hits), "commercial": len(usable), "candidates": cands, "selected": 0,
                        "sources": res["sources"]}
        if params.download_files and cands:
            await self._fetch_file(cands[0])

    async def _fetch_file(self, cand: dict) -> None:
        """Pobiera plik kandydata i czyta wymiary, wagę, czas (tylko serwisy z API do plików)."""
        if cand.get("file") or cand.get("file_error"):
            return
        prov = next((p for p in self.svc.models if p.name == cand["source"] and hasattr(p, "download")), None)
        if not prov:
            return
        try:
            got = await prov.download(self.svc.client, _hit(cand))
            if got:
                name, data = got
                cand["file"] = self._analyze(name, data)
        except Exception as e:  # noqa: BLE001
            cand["file_error"] = str(e)[:200]

    def _analyze(self, name: str, data: bytes, filament: str | None = None) -> dict:
        profile = self.svc.store.get_profile()
        fil, prn = profile.filament(filament), profile.printer()
        a = analyze_file(name, data, fil.density_g_cm3, prn.throughput_g_per_h)
        return {"name": name, **a.model_dump()}

    def _recompute(self, st: dict, params: FlowParams | None = None) -> None:
        params = params or FlowParams(**st["params"])
        profile = self.svc.store.get_profile()
        kws = {k["id"]: k for k in self.svc.store.list_keywords()}
        st["items"] = [compute_item(it, kws.get(it["keyword_id"], {}), params, profile) for it in st["items"]]
        st["items"].sort(key=lambda i: (not i.get("excluded"), i["final_score"]), reverse=True)
        st["plan"] = build_plan(st["items"], params, profile)
        st["summary"] = {
            "best": next((i["keyword"] for i in st["items"] if not i.get("excluded")), None),
            "items": len(st["items"]), "with_models": sum(1 for i in st["items"] if i["models"]["candidates"]),
        }

    def _compare(self, st: dict) -> None:
        prev = next((r for r in self.svc.store.list_flow_runs(10) if r["id"] != st["id"]), None)
        if not prev:
            return
        old = self.svc.store.get_flow_run(prev["id"]) or {}
        by_kw = {i["keyword"]: i for i in old.get("items", [])}
        for it in st["items"]:
            o = by_kw.get(it["keyword"])
            it["delta"] = None if not o else {
                "profit_day": round(it["profit_day"] - o.get("profit_day", 0), 2),
                "final_score": round(it["final_score"] - o.get("final_score", 0), 1), "new": False}
            if o is None:
                it["delta"] = {"new": True}
        st["compare"] = {"id": prev["id"], "created_at": prev["created_at"]}

    def _save(self, st: dict) -> None:
        data = {k: st[k] for k in ("items", "others", "plan", "compare", "summary") if k in st}
        self.svc.store.save_flow_run(st["id"], st["params"], data)

    # ------------------------------------------------------------ punkty kontrolne
    async def update(self, run_id: str, *, params: dict | None = None,
                     overrides: dict[int, ItemOverride] | None = None) -> dict:
        st = self.get(run_id)
        if not st:
            raise KeyError(run_id)
        async with self._locks.setdefault(run_id, asyncio.Lock()):
            if params:
                st["params"] = FlowParams(**{**st["params"], **params}).model_dump()
            p = FlowParams(**st["params"])
            for it in st["items"]:
                ov = (overrides or {}).get(it["keyword_id"])
                if not ov:
                    continue
                data = ov.model_dump(exclude_none=True)
                if "excluded" in data:
                    it["excluded"] = data.pop("excluded")
                if "selected" in data:
                    it["models"]["selected"] = data["selected"]
                    sel = data["selected"]
                    if 0 <= sel < len(it["models"]["candidates"]) and p.download_files:
                        await self._fetch_file(it["models"]["candidates"][sel])
                it["overrides"].update(data)
            self._recompute(st, p)
            self._save(st)
        return st

    async def reset_item(self, run_id: str, keyword_id: int) -> dict:
        st = self.get(run_id)
        for it in st["items"]:
            if it["keyword_id"] == keyword_id:
                it["overrides"] = {}
        return await self.update(run_id)

    async def upload(self, run_id: str, keyword_id: int, filename: str, data: bytes) -> dict:
        st = self.get(run_id)
        if not st:
            raise KeyError(run_id)
        it = next(i for i in st["items"] if i["keyword_id"] == keyword_id)
        a = await asyncio.to_thread(self._analyze, filename, data, it.get("spec", {}).get("filament"))
        ov = ItemOverride(unit_weight_g=a.get("unit_weight_g"), unit_time_h=a.get("unit_time_h"),
                          color_changes=a.get("color_changes"))
        if a.get("bbox_mm"):
            ov.size_x, ov.size_y, ov.size_z = a["bbox_mm"]
        it["uploaded_file"] = {k: a.get(k) for k in ("name", "kind", "exact", "objects", "note", "bbox_mm")}
        return await self.update(run_id, overrides={keyword_id: ov})

    async def add_item(self, run_id: str, keyword_id: int) -> dict:
        st = self.get(run_id)
        kw = self.svc.store.get_keyword(keyword_id)
        if not st or not kw:
            raise KeyError(keyword_id)
        if any(i["keyword_id"] == keyword_id for i in st["items"]):
            return st
        p = FlowParams(**st["params"])
        opp = await self.svc.evaluate_keyword(kw)
        it = self._new_item(opp)
        await self._models_for(it, p)
        st["items"].append(it)
        st["others"] = [o for o in st["others"] if o["keyword_id"] != keyword_id]
        return await self.update(run_id)


def _hit(cand: dict):
    from .schemas import ModelHit
    fields = set(ModelHit.model_fields)
    return ModelHit(**{k: v for k, v in cand.items() if k in fields})


__all__ = ["FlowRunner", "FlowParams", "ItemOverride", "compute_item", "build_plan", "STAGES", "pln"]
