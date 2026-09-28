"""Serwer FastAPI: REST API + interfejs w przeglądarce."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalog import QUICK_LINKS
from .config import Settings, get_settings
from .costing import CostInput, calculate
from .db import Store
from .fileparse import analyze_file
from .ip_risk import check_ip
from .profile import Profile, default_profile
from .seasonality import upcoming
from .services import Services

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 200 * 1024 * 1024


class KeywordIn(BaseModel):
    keyword: str = Field(min_length=2)
    keyword_en: str | None = None
    category: str | None = "Inne"
    weight_g: float = Field(50, gt=0)
    time_h: float = Field(2, gt=0)
    filament: str | None = "pla"
    post_min: float = 0
    color_changes: int = 0
    seasons: list[str] = Field(default_factory=lambda: ["all_year"])
    active: bool = True


class KeywordPatch(BaseModel):
    keyword_en: str | None = None
    category: str | None = None
    weight_g: float | None = Field(None, gt=0)
    time_h: float | None = Field(None, gt=0)
    filament: str | None = None
    post_min: float | None = None
    color_changes: int | None = None
    seasons: list[str] | None = None
    active: bool | None = None


class ScanIn(BaseModel):
    keyword_ids: list[int] | None = None
    refresh: bool = False


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = services or Services(settings, Store(settings.db_path))
        app.state.svc = svc
        task = None
        if settings.refresh_interval_hours > 0 and services is None:
            task = asyncio.create_task(_refresh_loop(svc, settings.refresh_interval_hours))
        yield
        if task:
            task.cancel()
        await svc.close()

    app = FastAPI(title="3D Trender", lifespan=lifespan)

    def svc() -> Services:
        return app.state.svc

    # ---------------------------------------------------------------- status i ustawienia
    @app.get("/api/status")
    def status():
        return {**svc().status(), "scan": svc().scan_state}

    @app.get("/api/profile")
    def get_profile() -> Profile:
        return svc().store.get_profile()

    @app.put("/api/profile")
    def put_profile(profile: Profile) -> Profile:
        svc().store.save_profile(profile)
        return profile

    @app.post("/api/profile/reset")
    def reset_profile() -> Profile:
        p = default_profile()
        svc().store.save_profile(p)
        return p

    # ---------------------------------------------------------------- frazy
    @app.get("/api/keywords")
    def list_keywords():
        return svc().store.list_keywords()

    @app.post("/api/keywords")
    def add_keyword(k: KeywordIn):
        try:
            return svc().store.add_keyword(k.model_dump())
        except Exception as e:  # noqa: BLE001 - np. duplikat
            raise HTTPException(400, f"Nie udało się dodać frazy: {e}") from e

    @app.patch("/api/keywords/{kid}")
    def patch_keyword(kid: int, k: KeywordPatch):
        res = svc().store.update_keyword(kid, k.model_dump(exclude_none=True))
        if not res:
            raise HTTPException(404, "Nie ma takiej frazy")
        return res

    @app.delete("/api/keywords/{kid}")
    def delete_keyword(kid: int):
        svc().store.delete_keyword(kid)
        return {"ok": True}

    # ---------------------------------------------------------------- okazje / trendy
    @app.get("/api/opportunities")
    def opportunities(sort: str = "score", category: str | None = None):
        return svc().opportunities(sort, category)

    @app.post("/api/scan")
    async def scan(body: ScanIn):
        if svc().scan_state["running"]:
            return {"started": False, "scan": svc().scan_state}
        asyncio.create_task(svc().scan(body.keyword_ids, use_cache=not body.refresh))
        await asyncio.sleep(0)
        return {"started": True, "scan": svc().scan_state}

    @app.post("/api/keywords/{kid}/evaluate")
    async def evaluate(kid: int, refresh: bool = False):
        kw = svc().store.get_keyword(kid)
        if not kw:
            raise HTTPException(404, "Nie ma takiej frazy")
        return await svc().evaluate_keyword(kw, use_cache=not refresh)

    @app.get("/api/trend")
    async def trend(q: str):
        return await svc().trend(q)

    @app.get("/api/history")
    def history(q: str):
        return svc().store.history(q)

    @app.get("/api/discover")
    async def discover(seeds: str = "druk 3d,wydruk 3d,3d printed"):
        return await svc().discover([s.strip() for s in seeds.split(",") if s.strip()])

    @app.get("/api/seasons")
    def seasons(days: int = 120):
        return upcoming(days=days)

    # ---------------------------------------------------------------- konkurencja
    @app.get("/api/market")
    async def market(q: str, q_en: str | None = None, refresh: bool = False):
        res = await svc().market(q, q_en, use_cache=not refresh)
        return {**res, "ip": check_ip(q, q_en).model_dump(), "links": _links("market", q)}

    # ---------------------------------------------------------------- modele
    @app.get("/api/models")
    async def models(q: str, commercial_only: bool = False, max_license_cost: float | None = None,
                     sort: str = "score", with_market: bool = True, weight_g: float | None = None,
                     time_h: float | None = None, filament: str | None = None):
        res = await svc().search_models(q, commercial_only=commercial_only, max_license_cost=max_license_cost,
                                        sort=sort, with_market=with_market, weight_g=weight_g, time_h=time_h,
                                        filament=filament)
        return {**res, "links": _links("models", q)}

    # ---------------------------------------------------------------- kalkulator
    @app.post("/api/cost")
    def cost(inp: CostInput):
        return calculate(inp, svc().store.get_profile())

    @app.post("/api/analyze-file")
    async def analyze(file: UploadFile = File(...), filament_id: str | None = Form(None),
                      printer_id: str | None = Form(None), infill: float = Form(0.15)):
        data = await file.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Plik za duży (max 200 MB)")
        profile = svc().store.get_profile()
        fil, prn = profile.filament(filament_id), profile.printer(printer_id)
        try:
            res = await asyncio.to_thread(analyze_file, file.filename or "", data, fil.density_g_cm3,
                                          prn.throughput_g_per_h, infill)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001 - uszkodzony zip/xml
            raise HTTPException(400, f"Nie udało się odczytać pliku: {e}") from e
        calc = None
        if res.weight_g and res.print_time_h:
            calc = calculate(CostInput(weight_g=res.weight_g, print_time_h=res.print_time_h, filament_id=fil.id,
                                       printer_id=prn.id, color_changes=res.color_changes or 0), profile)
        return {"analysis": res, "cost": calc}

    # ---------------------------------------------------------------- interfejs
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


def _links(kind: str, q: str) -> dict:
    qp = quote_plus(q)
    return {name: url.format(q=qp, q_dash=quote_plus(q.replace(" ", "-"))) for name, url in QUICK_LINKS[kind].items()}


async def _refresh_loop(svc: Services, hours: float) -> None:
    """Pierwszy skan przy starcie (jeśli brak wyników lub są stare), potem co `hours` godzin."""
    await asyncio.sleep(5)
    while True:
        items = svc.store.list_opportunities()
        oldest = min((i["updated_at"] for i in items), default=0)
        if not items or time.time() - oldest > hours * 3600:
            await svc.scan()
        await asyncio.sleep(max(hours * 3600 / 4, 600))


app = create_app()


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("trender.main:app", host=s.host, port=s.port)


if __name__ == "__main__":
    run()
