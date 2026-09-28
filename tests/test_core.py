import datetime as dt
import io
import struct
import zipfile

import pytest

from trender.costing import CostInput, calculate, compute_cost
from trender.fileparse import analyze_file, parse_duration, parse_gcode
from trender.ip_risk import check_ip
from trender.licensing import classify_license
from trender.profile import default_profile
from trender.scoring import market_stats, opportunity_score
from trender.schemas import Listing
from trender.seasonality import easter, season_boost, upcoming


def test_cost_breakdown_matches_hand_calculation():
    p = default_profile()
    c = compute_cost(CostInput(weight_g=100, print_time_h=4, printer_id="p1s", filament_id="pla"), p)
    # 100 g * 1.05 odpad = 105 g * 70 zł/kg
    assert c.material == pytest.approx(7.35)
    machine_h = 4 + 6 / 60
    assert c.machine_time_h == pytest.approx(machine_h, abs=1e-3)
    assert c.energy == pytest.approx(0.11 * machine_h * 1.10, abs=0.01)
    assert c.depreciation == pytest.approx(3900 / 6000 * machine_h, abs=0.01)
    production = 7.35 + 0.11 * machine_h * 1.10 + 3900 / 6000 * machine_h + 0.25 * machine_h
    assert c.total == pytest.approx(production / 0.95 + 2.5, abs=0.02)


def test_units_per_plate_and_purge_reduce_or_add_cost():
    p = default_profile()
    one = compute_cost(CostInput(weight_g=10, print_time_h=0.5), p)
    many = compute_cost(CostInput(weight_g=10, print_time_h=0.5, units_per_plate=8), p)
    assert many.machine_time_h < one.machine_time_h
    colors = compute_cost(CostInput(weight_g=10, print_time_h=0.5, color_changes=10, printer_id="p1s"), p)
    assert colors.filament_g == pytest.approx(10 * 1.05 + 10 * 0.8)
    # na płycie z 5 sztukami płukanie i czas zmian dzielą się na 5
    batch = compute_cost(CostInput(weight_g=10, print_time_h=0.5, color_changes=10, units_per_plate=5,
                                   printer_id="p1s"), p)
    assert batch.filament_g == pytest.approx(10 * 1.05 + 10 * 0.8 / 5)
    assert batch.machine_time_h == pytest.approx(0.5 + (6 / 60 + 10 * 40 / 3600) / 5, abs=1e-3)


def test_suggested_price_hits_target_margin_and_profit_at_price():
    p = default_profile()
    r = calculate(CostInput(weight_g=50, print_time_h=2, channel="allegro", sale_price_pln=40), p)
    assert r.suggested.margin >= p.target_margin - 0.02
    assert r.at_price.fees == pytest.approx(40 * 0.11, abs=0.01)
    assert r.at_price.profit == pytest.approx(40 - 4.4 - r.cost.total, abs=0.01)
    p.vat_payer = True
    r2 = calculate(CostInput(weight_g=50, print_time_h=2, channel="allegro", sale_price_pln=40), p)
    assert r2.at_price.vat == pytest.approx(40 * 0.23 / 1.23, abs=0.01)


@pytest.mark.parametrize("raw,code,status", [
    ("Creative Commons - Attribution", None, "attribution"),
    ("Creative Commons - Attribution - Non-Commercial", None, "non_commercial"),
    ("CC BY-NC-SA 4.0", None, "non_commercial"),
    ("Creative Commons - Attribution - No Derivatives", None, "no_derivatives"),
    ("Creative Commons - Public Domain Dedication", None, "allowed"),
    ("CC0", None, "allowed"),
    ("Standard Digital File License", None, "non_commercial"),
    ("GNU - GPL", None, "attribution"),
    ("Something odd", None, "unknown"),
    (None, "cults_cu", "allowed"),
    ("Cults - Private use", "cults_private", "non_commercial"),
])
def test_license_classification(raw, code, status):
    assert classify_license(raw, code).status == status


def test_ip_risk():
    assert check_ip("Pikachu breloczek").level == "high"
    assert check_ip("stojak na pada PS5").level == "medium"
    assert check_ip("organizer na biurko").level == "none"
    # nie łapie fragmentów słów
    assert check_ip("marionetka").level == "none"


def test_seasonality():
    assert easter(2026) == dt.date(2026, 4, 5)
    assert easter(2027) == dt.date(2027, 3, 28)
    boost, name = season_boost(["halloween"], dt.date(2026, 10, 15))
    assert name == "Halloween" and boost > 0.7
    assert season_boost(["easter"], dt.date(2026, 9, 28))[0] == 0
    ev = upcoming(dt.date(2026, 9, 28), days=100)
    assert ev[0]["name"] == "Halloween" and ev[0]["in_window"]


def test_market_stats_and_score():
    ls = [Listing(source="a", title="x", price=p, price_pln=p, sold=s) for p, s in [(10, 1), (20, 5), (30, 0), (40, 10)]]
    st = market_stats(ls)
    assert st["median"] == 25 and st["sold_sum"] == 16 and st["count"] == 4
    p = default_profile()
    kw = dict(total_listings=100, sold_sum=200, favorites_avg=None, trend_momentum=0.4, trend_level=70,
              season_boost=0.9, season_name="Halloween", profit_per_hour=30, profit=20, market_price=50,
              ip=check_ip("dynia"), profile=p)
    good = opportunity_score(**kw)
    bad = opportunity_score(**{**kw, "profit": -5, "profit_per_hour": -2})
    risky = opportunity_score(**{**kw, "ip": check_ip("pokemon")})
    assert good["score"] > 70 and good["tier"]["id"] == "best"
    assert bad["score"] <= 30 and risky["score"] < good["score"] / 2


# ------------------------------------------------------------------ pliki

def _cube_tris(s=20.0):
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v, faces


def _binary_stl():
    v, faces = _cube_tris()
    out = bytearray(b"\0" * 80) + struct.pack("<I", len(faces))
    for f in faces:
        out += struct.pack("<3f", 0, 0, 0)
        for i in f:
            out += struct.pack("<3f", *v[i])
        out += b"\0\0"
    return bytes(out)


def test_stl_volume_and_estimate():
    a = analyze_file("cube.stl", _binary_stl(), density=1.24, throughput_g_h=35, infill=0.15)
    assert a.volume_cm3 == pytest.approx(8.0)
    assert a.area_cm2 == pytest.approx(24.0)
    assert a.bbox_mm == [20, 20, 20]
    shell = 24 * 0.1
    assert a.weight_g == pytest.approx((shell + (8 - shell) * 0.15) * 1.24, abs=0.1)
    assert not a.exact


def test_ascii_stl():
    v, faces = _cube_tris(10)
    lines = ["solid c"] + [f"facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {v[i][0]} {v[i][1]} {v[i][2]}\n" for i in f) + "endloop\nendfacet" for f in faces] + ["endsolid"]
    a = analyze_file("c.stl", "\n".join(lines).encode())
    assert a.volume_cm3 == pytest.approx(1.0)


def test_gcode_bambu_and_prusa():
    bambu = "; HEADER_BLOCK_START\n; model printing time: 1h 2m 3s; total estimated time: 1h 10m 30s\n; total filament weight [g] : 25.53\n; filament_type = PLA\n"
    a = parse_gcode(bambu)
    assert a.weight_g == 25.53 and a.print_time_h == pytest.approx(1 + 10 / 60 + 30 / 3600, abs=1e-3) and a.exact
    prusa = "G1 X0\n; filament used [g] = 12.3, 4.2\n; estimated printing time (normal mode) = 2h 5m 0s\n"
    b = parse_gcode(prusa)
    assert b.weight_g == pytest.approx(16.5) and b.print_time_h == pytest.approx(2 + 5 / 60, abs=1e-3)
    cura = ";TIME:5400\n;Filament used: 2.5m\n"
    c = parse_gcode(cura)
    assert c.print_time_h == 1.5 and c.weight_g == pytest.approx(2500 * 3.14159 * 0.875 ** 2 / 1000 * 1.24, abs=0.1)
    assert parse_duration("1d 1h") == 25


def test_3mf_sliced_and_mesh():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Metadata/slice_info.config", """<?xml version="1.0"?><config>
          <plate><metadata key="index" value="1"/><metadata key="prediction" value="3600"/><metadata key="weight" value="20.5"/>
          <filament id="1" type="PETG" used_g="20.5"/></plate>
          <plate><metadata key="index" value="2"/><metadata key="prediction" value="1800"/><metadata key="weight" value="9.5"/></plate></config>""")
    a = analyze_file("proj.gcode.3mf", buf.getvalue())
    assert a.exact and a.weight_g == 30 and a.print_time_h == 1.5 and a.plates == 2 and a.filament_type == "PETG"

    v, faces = _cube_tris()
    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    verts = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in v)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    model = f'<model xmlns="{ns}"><resources><object id="1"><mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh></object></resources></model>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("3D/3dmodel.model", model)
    m = analyze_file("model.3mf", buf.getvalue())
    assert m.kind == "3mf-mesh" and m.volume_cm3 == pytest.approx(8.0)


def test_bad_file():
    with pytest.raises(ValueError):
        analyze_file("x.obj", b"")
