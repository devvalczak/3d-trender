"""Odczyt wagi i czasu druku z plików: G-code, 3MF (Bambu Studio / Orca) i STL.

- Pocięty 3MF / G-code: dokładne wartości ze slicera.
- STL / niepocięty 3MF: szacunek z objętości i powierzchni siatki.
"""

from __future__ import annotations

import io
import re
import struct
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from pydantic import BaseModel


class FileAnalysis(BaseModel):
    kind: str  # gcode / 3mf-sliced / 3mf-mesh / stl
    exact: bool  # True gdy wartości pochodzą ze slicera
    weight_g: float | None = None
    print_time_h: float | None = None
    filament_type: str | None = None
    volume_cm3: float | None = None
    area_cm2: float | None = None
    bbox_mm: list[float] | None = None
    triangles: int | None = None
    plates: int | None = None
    objects: int | None = None  # ile obiektów (sztuk) jest na płycie w projekcie
    unit_weight_g: float | None = None  # waga / czas na jedną sztukę
    unit_time_h: float | None = None
    color_changes: int | None = None  # zmiany koloru na płytę
    note: str = ""

    def per_unit(self) -> "FileAnalysis":
        n = max(self.objects or 1, 1)
        self.unit_weight_g = round(self.weight_g / n, 2) if self.weight_g else None
        self.unit_time_h = round(self.print_time_h / n, 3) if self.print_time_h else None
        return self


# ---------------------------------------------------------------- G-code

_DURATION = re.compile(r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?")


def parse_duration(text: str) -> float | None:
    """'1d 2h 3m 4s' -> godziny."""
    m = _DURATION.search(text.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return (d * 86400 + h * 3600 + mi * 60 + s) / 3600


def _sum_numbers(text: str) -> float:
    return sum(float(x) for x in re.findall(r"\d+(?:\.\d+)?", text))


def parse_gcode(text: str, density: float = 1.24) -> FileAnalysis:
    weight = time_h = None
    ftype = None

    m = re.search(r";\s*total filament (?:weight|used) \[g\]\s*[:=]\s*([\d.,\s]+)", text)
    if not m:
        m = re.search(r";\s*filament used \[g\]\s*[:=]\s*([\d.,\s]+)", text)
    if m:
        weight = _sum_numbers(m.group(1).split("\n")[0])

    m = re.search(r";\s*total estimated time:\s*([^;\n]+)", text)  # Bambu Studio
    if not m:
        m = re.search(r";\s*estimated printing time \(normal mode\)\s*=\s*([^\n]+)", text)  # Prusa/Orca
    if m:
        time_h = parse_duration(m.group(1))
    else:
        m = re.search(r";TIME:(\d+)", text)  # Cura
        if m:
            time_h = int(m.group(1)) / 3600

    if weight is None:
        m = re.search(r";Filament used:\s*([\d.]+)m", text)  # Cura: długość w metrach, 1.75 mm
        if m:
            length_mm = float(m.group(1)) * 1000
            weight = length_mm * np.pi * 0.875**2 / 1000 * density

    m = re.search(r";\s*filament_type\s*=\s*([^\n;]+)", text)
    if m:
        ftype = m.group(1).strip().split(";")[0]

    changes = len(re.findall(r"^M620 S\d", text, flags=re.M))  # zmiany filamentu AMS w Bambu
    return FileAnalysis(kind="gcode", exact=weight is not None and time_h is not None,
                        weight_g=_round(weight), print_time_h=_round(time_h, 3), filament_type=ftype,
                        color_changes=max(changes - 1, 0) if changes else None)


def _gcode_head_tail(data: bytes, size: int = 400_000) -> str:
    if len(data) <= 2 * size:
        return data.decode("utf-8", "ignore")
    return data[:size].decode("utf-8", "ignore") + "\n" + data[-size:].decode("utf-8", "ignore")


# ---------------------------------------------------------------- siatki

def mesh_stats(tris: np.ndarray) -> tuple[float, float, list[float]]:
    """tris: (n, 3, 3) w mm. Zwraca objętość cm3, pole cm2, wymiary mm."""
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    volume = abs(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)
    area = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1).sum() / 2.0
    pts = tris.reshape(-1, 3)
    bbox = (pts.max(axis=0) - pts.min(axis=0)).tolist() if len(pts) else [0, 0, 0]
    return volume / 1000, area / 100, [round(x, 1) for x in bbox]


def read_stl(data: bytes) -> np.ndarray:
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + n * 50 == len(data):
            dtype = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
            return np.frombuffer(data, dtype=dtype, count=n, offset=84)["v"].astype(np.float64)
    text = data.decode("utf-8", "ignore")
    nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if not nums or len(nums) % 3:
        raise ValueError("Nieprawidłowy plik STL")
    return np.array(nums, dtype=np.float64).reshape(-1, 3, 3)


def _mesh_tris(mesh: ET.Element) -> np.ndarray | None:
    verts = [(float(v.get("x")), float(v.get("y")), float(v.get("z"))) for v in mesh.iter() if v.tag.endswith("vertex")]
    idx = [(int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))) for t in mesh.iter() if t.tag.endswith("triangle")]
    if not verts or not idx:
        return None
    return np.array(verts)[np.array(idx)]


def read_3mf_objects(zf: zipfile.ZipFile) -> list[np.ndarray]:
    """Siatki obiektów z 3MF. Plik w 3D/Objects/ (Bambu Studio) = jeden obiekt, w pliku głównym każdy <object>."""
    objects = []
    for name in zf.namelist():
        if not name.lower().endswith(".model"):
            continue
        root = ET.fromstring(zf.read(name))
        per_file = []
        for obj in root.iter():
            if not obj.tag.endswith("object"):
                continue
            meshes = [m for m in obj if m.tag.endswith("mesh")]
            tris = [t for m in meshes if (t := _mesh_tris(m)) is not None]
            if tris:
                per_file.append(np.concatenate(tris))
        if "/objects/" in name.lower() and per_file:
            objects.append(np.concatenate(per_file))
        else:
            objects.extend(per_file)
    return objects


def read_3mf_mesh(zf: zipfile.ZipFile) -> np.ndarray:
    objects = read_3mf_objects(zf)
    if not objects:
        raise ValueError("Brak siatki w pliku 3MF")
    return np.concatenate(objects)


def estimate_from_mesh(volume_cm3: float, area_cm2: float, density: float, throughput_g_h: float,
                       infill: float = 0.15, shell_mm: float = 1.0) -> tuple[float, float]:
    """Szacunek slicera: skorupa (ściany + góra/dół) pełna, wnętrze wypełnione w `infill`."""
    shell = min(volume_cm3, area_cm2 * shell_mm / 10)
    material_cm3 = shell + (volume_cm3 - shell) * infill
    weight = material_cm3 * density
    return weight, weight / throughput_g_h


def _round(x: float | None, n: int = 2) -> float | None:
    return round(x, n) if x is not None else None


# ---------------------------------------------------------------- wejście

def analyze_file(filename: str, data: bytes, density: float = 1.24, throughput_g_h: float = 35,
                 infill: float = 0.15) -> FileAnalysis:
    name = filename.lower()
    if name.endswith((".gcode", ".gco", ".g", ".bgcode")):
        if name.endswith(".bgcode"):
            raise ValueError("Binarny G-code (.bgcode) nie jest obsługiwany: wyeksportuj zwykły .gcode")
        return parse_gcode(_gcode_head_tail(data), density).per_unit()

    if name.endswith(".3mf"):
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        objects = read_3mf_objects(zf)
        unit = max(objects, key=lambda t: mesh_stats(t)[0]) if objects else None
        if "Metadata/slice_info.config" in names:
            res = _parse_slice_info(zf.read("Metadata/slice_info.config"))
            if res:
                if unit is not None:
                    res.bbox_mm = mesh_stats(unit)[2]
                plate_gcode = next((n for n in names if n.lower().endswith(".gcode")), None)
                if plate_gcode:
                    res.color_changes = parse_gcode(_gcode_head_tail(zf.read(plate_gcode))).color_changes
                return res.per_unit()
        gcodes = [n for n in names if n.lower().endswith(".gcode")]
        if gcodes:
            weights = times = 0.0
            last = None
            for g in gcodes:
                last = parse_gcode(_gcode_head_tail(zf.read(g)), density)
                weights += last.weight_g or 0
                times += last.print_time_h or 0
            return FileAnalysis(kind="3mf-sliced", exact=True, weight_g=round(weights, 2),
                                print_time_h=round(times, 3), filament_type=last.filament_type if last else None,
                                plates=len(gcodes), color_changes=last.color_changes if last else None,
                                objects=len(objects) or None,
                                bbox_mm=mesh_stats(unit)[2] if unit is not None else None).per_unit()
        if unit is None:
            raise ValueError("Brak siatki w pliku 3MF")
        res = _mesh_result("3mf-mesh", unit, density, throughput_g_h, infill).per_unit()
        res.objects = len(objects)
        if len(objects) > 1:
            res.note += f" Projekt ma {len(objects)} obiektów: liczę największy jako jedną sztukę."
        return res

    if name.endswith(".stl"):
        return _mesh_result("stl", read_stl(data), density, throughput_g_h, infill).per_unit()

    raise ValueError("Obsługiwane pliki: .stl, .3mf, .gcode")


def _mesh_result(kind: str, tris: np.ndarray, density: float, throughput: float, infill: float) -> FileAnalysis:
    vol, area, bbox = mesh_stats(tris)
    w, t = estimate_from_mesh(vol, area, density, throughput, infill)
    return FileAnalysis(kind=kind, exact=False, weight_g=round(w, 1), print_time_h=round(t, 2), objects=1,
                        volume_cm3=round(vol, 2), area_cm2=round(area, 1), bbox_mm=bbox, triangles=len(tris),
                        note=f"Szacunek z siatki (wypełnienie {int(infill * 100)}%, skorupa ok. 1 mm). "
                             "Dla dokładnych wartości wgraj pocięty .3mf z Bambu Studio.")


def _parse_slice_info(xml: bytes) -> FileAnalysis | None:
    root = ET.fromstring(xml)
    weight = seconds = 0.0
    plates = 0
    objects = 0
    ftypes = []
    for plate in root.iter("plate"):
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        if "prediction" not in meta and "weight" not in meta:
            continue
        plates += 1
        seconds += float(meta.get("prediction") or 0)
        weight += float(meta.get("weight") or 0)
        if not objects:
            objects = len([o for o in plate.iter("object") if o.get("skipped", "false") != "true"])
        for f in plate.iter("filament"):
            if f.get("type"):
                ftypes.append(f.get("type"))
    if not plates:
        return None
    return FileAnalysis(kind="3mf-sliced", exact=True, weight_g=round(weight, 2),
                        print_time_h=round(seconds / 3600, 3), plates=plates, objects=objects if plates == 1 else None,
                        filament_type=ftypes[0] if ftypes else None,
                        note="Wartości ze slicera. Czas obejmuje wszystkie płyty w projekcie.")
