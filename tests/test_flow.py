import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from trender.db import Store
from trender.flow import FlowParams, build_plan
from trender.main import create_app
from trender.plate import layout
from trender.profile import default_profile
from trender.schedule import optimize
from trender.services import Services


def test_plate_layout_grid_rotation_and_exclusion():
    assert layout(59, 59).units == 9  # 3x3 na 246 mm użytecznej powierzchni
    assert layout(18, 18).units == 100
    assert layout(300, 20).units == 0 and not layout(300, 20).fits
    # układ mieszany (część obrócona) bije czystą siatkę
    mixed = layout(50, 30)
    assert mixed.units > max((251 // 55) * (251 // 35), (251 // 35) * (251 // 55))
    # strefa wykluczenia P1S zabiera obiekty w rogu
    assert layout(50, 30, exclude=[[0, 0, 18, 28]]).units < mixed.units
    # pozycje nie nachodzą na siebie i mieszczą się na stole
    l = layout(40, 25, spacing=5)
    for i, a in enumerate(l.positions):
        assert a[0] >= 5 and a[1] >= 5 and a[0] + a[2] <= 251 and a[1] + a[3] <= 251
        for b in l.positions[i + 1:]:
            assert a[0] + a[2] + 5 <= b[0] + 1e-6 or b[0] + b[2] + 5 <= a[0] + 1e-6 or \
                a[1] + a[3] + 5 <= b[1] + 1e-6 or b[1] + b[3] + 5 <= a[1] + 1e-6


def test_schedule_optimum_beats_simple_and_respects_limits():
    best, simple = optimize(max_units=12, unit_h=0.5, plate_extra_h=0.1, unit_profit=lambda n: 10.0,
                            attended_hours=10, allow_night=True, swap_min=5)
    assert simple.day_plates == 1 and simple.units_per_day == 12
    assert best.profit_per_day > simple.profit_per_day
    swap = 5 / 60
    assert best.day_plates * (best.day_plate_h + swap) <= 10 + 1e-9
    assert best.day_plates * (best.day_plate_h + swap) + best.night_plate_h <= 24 + 1e-9
    no_night, _ = optimize(max_units=12, unit_h=0.5, plate_extra_h=0.1, unit_profit=lambda n: 10.0,
                           attended_hours=10, allow_night=False, swap_min=5)
    assert no_night.day_plates * (no_night.day_plate_h + swap) + no_night.night_plate_h <= 10 + 1e-9
    assert no_night.profit_per_day < best.profit_per_day


def test_plan_respects_demand_cap():
    params = FlowParams(plan_days=7)
    sched = {"day_units_per_plate": 10, "day_plates": 2, "night_units": 10, "units_per_day": 30, "label": "x"}

    def item(name, profit_day, cap):
        return {"keyword": name, "excluded": False, "profit_day": profit_day, "units_day": 30, "cap_day": cap,
                "best_variant": "single", "spec": {"filament": "pla"},
                "variants": [{"id": "single", "label": "1", "schedule": sched, "cost": {"filament_g": 10}}]}
    plan = build_plan([item("a", 300, 2), item("b", 200, None)], params, default_profile())
    a, b = plan["rows"]
    assert a["units"] == 14 and a["days"] == pytest.approx(0.5, abs=0.05)
    assert b["days"] == pytest.approx(6.5, abs=0.1)  # reszta tygodnia dla produktu bez limitu
    assert plan["idle_days"] == 0


def _run(c, params):
    st = c.post("/api/flow", json=params).json()
    for _ in range(300):
        st = c.get(f"/api/flow/{st['id']}").json()
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("przebieg się nie skończył")


def test_flow_api_end_to_end(settings):
    svc = Services(settings, Store(settings.db_path))
    with TestClient(create_app(settings, svc)) as c:
        params = c.get("/api/flow/defaults").json()["params"]
        params["top_n"] = 5
        st = _run(c, params)
        assert st["status"] == "done", st.get("error")
        assert len(st["items"]) == 5 and st["others"]
        it = st["items"][0]
        assert it["plate"]["units"] >= 1 and it["variants"] and it["listing"]["title"]
        assert len(it["listing"]["title"]) <= 75
        assert st["plan"]["rows"]
        scores = [i["final_score"] for i in st["items"]]
        assert scores == sorted(scores, reverse=True)

        kid = it["keyword_id"]
        # punkt kontrolny: mniejszy obiekt -> więcej sztuk na płycie
        st2 = c.patch(f"/api/flow/{st['id']}", json={"overrides": {str(kid): {"size_x": 20, "size_y": 20}}}).json()
        it2 = next(i for i in st2["items"] if i["keyword_id"] == kid)
        assert it2["plate"]["units"] > it["plate"]["units"] and it2["spec"]["size_source"] == "ręcznie"
        # wykluczenie z planu
        st3 = c.patch(f"/api/flow/{st['id']}", json={"overrides": {str(kid): {"excluded": True}}}).json()
        assert all(r["keyword"] != it["keyword"] for r in st3["plan"]["rows"])
        assert st3["items"][-1]["keyword_id"] == kid
        # zmiana parametrów bez ponownego odpytywania API
        st4 = c.patch(f"/api/flow/{st['id']}", json={"params": {"attended_hours": 4, "allow_night": False}}).json()
        assert st4["params"]["attended_hours"] == 4
        # wgranie pocięty 3MF z 4 obiektami -> waga/czas na sztukę
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Metadata/slice_info.config", '<config><plate><metadata key="prediction" value="14400"/>'
                       '<metadata key="weight" value="80"/><object name="a"/><object name="b"/><object name="c"/>'
                       '<object name="d"/></plate></config>')
        st5 = c.post(f"/api/flow/{st['id']}/items/{kid}/file", files={"file": ("p.gcode.3mf", buf.getvalue())}).json()
        it5 = next(i for i in st5["items"] if i["keyword_id"] == kid)
        assert it5["spec"]["unit_weight_g"] == 20 and it5["spec"]["unit_time_h"] == 1
        # dodanie frazy spoza lejka
        other = st["others"][0]["keyword_id"]
        st6 = c.post(f"/api/flow/{st['id']}/items/{other}").json()
        assert any(i["keyword_id"] == other for i in st6["items"])
        # reset korekt
        st7 = c.post(f"/api/flow/{st['id']}/items/{kid}/reset").json()
        assert next(i for i in st7["items"] if i["keyword_id"] == kid)["overrides"] == {}

        # drugi przebieg: historia i porównanie
        st8 = _run(c, params)
        assert st8["compare"]["id"] == st["id"] and "delta" in st8["items"][0]
        runs = c.get("/api/flow/runs").json()
        assert {r["id"] for r in runs} >= {st["id"], st8["id"]}
        assert c.get("/api/flow/nope").status_code == 404
