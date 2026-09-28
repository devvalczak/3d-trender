import time

from fastapi.testclient import TestClient

from trender.db import Store
from trender.main import create_app
from trender.services import Services


def make(settings):
    svc = Services(settings, Store(settings.db_path))
    return TestClient(create_app(settings, svc))


def test_full_flow_demo(settings):
    with make(settings) as c:
        st = c.get("/api/status").json()
        assert all(p["demo"] for p in st["markets"])

        kws = c.get("/api/keywords").json()
        assert len(kws) >= 30
        ids = [k["id"] for k in kws[:5]]
        assert c.post("/api/scan", json={"keyword_ids": ids}).json()["started"]
        for _ in range(100):
            if not c.get("/api/status").json()["scan"]["running"]:
                break
            time.sleep(0.05)
        opps = c.get("/api/opportunities").json()
        assert len(opps) == 5
        scores = [o["score"] for o in opps]
        assert scores == sorted(scores, reverse=True)
        o = opps[0]
        assert o["demo"] and o["reasons"] and o["cost"]["total"] > 0 and o["at_market"]
        by_profit = c.get("/api/opportunities?sort=profit_h").json()
        ph = [x["at_market"]["profit_per_hour"] for x in by_profit]
        assert ph == sorted(ph, reverse=True)
        assert c.get("/api/history", params={"q": o["keyword"]}).json()

        m = c.get("/api/market", params={"q": "organizer na biurko"}).json()
        assert m["stats"]["median"] > 0 and "Allegro" in m["links"]

        r = c.get("/api/models", params={"q": "organizer na biurko", "commercial_only": True}).json()
        assert r["hits"] and all(h["license_total_pln"] is not None for h in r["hits"])
        s = [h["score"] for h in r["hits"]]
        assert s == sorted(s, reverse=True)

        cost = c.post("/api/cost", json={"weight_g": 40, "print_time_h": 1.5, "sale_price_pln": 35}).json()
        assert cost["at_price"]["profit"] < 35

        gcode = b"; total filament weight [g] : 12.5\n; total estimated time: 1h 0m 0s\n"
        a = c.post("/api/analyze-file", files={"file": ("x.gcode", gcode)}).json()
        assert a["analysis"]["weight_g"] == 12.5 and a["cost"]["cost"]["total"] > 0
        assert c.post("/api/analyze-file", files={"file": ("x.obj", b"")}).status_code == 400

        assert c.get("/api/seasons").json()
        assert c.get("/api/discover").json()
        assert c.get("/api/trend", params={"q": "lampa księżyc"}).json()["points"]


def test_keywords_and_profile_crud(settings):
    with make(settings) as c:
        k = c.post("/api/keywords", json={"keyword": "podstawka pod laptop", "weight_g": 120, "time_h": 4}).json()
        assert c.post("/api/keywords", json={"keyword": "podstawka pod laptop"}).status_code == 400
        k2 = c.patch(f"/api/keywords/{k['id']}", json={"weight_g": 90, "active": False}).json()
        assert k2["weight_g"] == 90 and k2["active"] is False
        c.delete(f"/api/keywords/{k['id']}")
        assert all(x["id"] != k["id"] for x in c.get("/api/keywords").json())

        p = c.get("/api/profile").json()
        p["energy_price_kwh_pln"] = 2.0
        assert c.put("/api/profile", json=p).json()["energy_price_kwh_pln"] == 2.0
        assert c.get("/api/profile").json()["energy_price_kwh_pln"] == 2.0
        assert c.post("/api/profile/reset").json()["energy_price_kwh_pln"] == 1.10
        assert c.get("/").status_code == 200 and c.get("/static/app.js").status_code == 200
