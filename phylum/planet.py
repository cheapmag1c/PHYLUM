from __future__ import annotations

import math
import random
from typing import Any

from .constants import GRID_COLS, GRID_ROWS, MAX_SCARS
from .utils import clamp, deterministic_rng, mean, smoothstep, stable_int


def _noise(x: float, y: float, seed: int, scale: float = 1.0) -> float:
    """Cheap deterministic smooth-ish pseudo-noise in roughly -1..1."""
    p = (seed % 10007) / 10007.0 * math.tau
    return (
        0.48 * math.sin((x * 1.31 + y * 0.77) * scale + p)
        + 0.31 * math.cos((x * 0.53 - y * 1.67) * scale - p * 0.7)
        + 0.21 * math.sin((x * 2.47 + y * 2.11) * scale + p * 1.3)
    )


def initialize_plates(seed: int, env: dict[str, Any]) -> dict[str, Any]:
    rng = deterministic_rng(seed, 0, "planet", "plates")
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    plates = []
    for i in range(7):
        angle = rng.random() * math.tau
        speed = rng.uniform(0.018, 0.055)
        plates.append({
            "id": f"plate-{i+1:02d}",
            "cx": round(rng.uniform(0.05, 0.95) * w, 4),
            "cy": round(rng.uniform(0.06, 0.94) * h, 4),
            "vx": round(math.cos(angle) * speed, 6),
            "vy": round(math.sin(angle) * speed, 6),
            "phase": round(rng.random() * math.tau, 6),
            "continental": rng.random() < 0.62,
            "buoyancy": round(rng.uniform(-0.12, 0.19), 4),
        })
    return {
        "schema_version": 2,
        "sea_level": 0.47,
        "geology_clock": 0.0,
        "drift_scale": 0.22,
        "plates": plates,
        "history": [],
    }


def plate_at(plates: dict[str, Any], x: float, y: float, env: dict[str, Any]) -> dict[str, Any]:
    plist = plates.get("plates", [])
    if not plist:
        return {"id": "plate-00", "cx": 0, "cy": 0, "vx": 0, "vy": 0, "phase": 0, "continental": True, "buoyancy": 0}
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    def dist2(p: dict[str, Any]) -> float:
        dx = abs(x - float(p["cx"]))
        dx = min(dx, max(0.0, w - dx))
        dy = abs(y - float(p["cy"]))
        return dx * dx + dy * dy
    return min(plist, key=dist2)


def plate_boundary_strength(plates: dict[str, Any], x: float, y: float, env: dict[str, Any]) -> float:
    plist = plates.get("plates", [])
    if len(plist) < 2:
        return 0.0
    w = float(env.get("width", 160))
    ds = []
    for p in plist:
        dx = abs(x - float(p["cx"]))
        dx = min(dx, max(0.0, w - dx))
        dy = y - float(p["cy"])
        ds.append(math.hypot(dx, dy))
    ds.sort()
    gap = ds[1] - ds[0]
    return clamp(1.0 - gap / 12.0, 0.0, 1.0)


def geography_at(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> dict[str, Any]:
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    nx, ny = x / max(w, 1), y / max(h, 1)
    plate = plate_at(plates, x, y, env)
    boundary = plate_boundary_strength(plates, x, y, env)
    drift = float(plates.get("geology_clock", 0.0))
    # Multi-scale terrain moves very slowly with plate phase/drift.
    base = 0.50 + 0.23 * _noise(nx * math.tau + drift * 0.0007, ny * math.tau, seed, 1.0)
    detail = 0.09 * _noise(nx * math.tau * 2.8, ny * math.tau * 2.8, seed ^ 0xA51C, 1.0)
    plate_bias = float(plate.get("buoyancy", 0.0)) + (0.055 if plate.get("continental") else -0.07)
    uplift = boundary * (0.09 + 0.08 * abs(float(plate.get("vx", 0))) / 0.055)
    elevation = base + detail + plate_bias + uplift
    # Keep the three ancestral regions habitable after migration from v0.3.
    for refuge in env.get("ancestral_refugia", []):
        dx = x - float(refuge.get("x", 0))
        dy = y - float(refuge.get("y", 0))
        r = max(1.0, float(refuge.get("radius", 11)))
        d = math.hypot(dx, dy)
        if d < r:
            elevation += 0.14 * (1 - d / r)
    sea = float(plates.get("sea_level", 0.47))
    land = elevation >= sea
    depth = clamp((sea - elevation) / 0.35, 0.0, 1.0)
    relief = clamp((elevation - sea) / 0.42, 0.0, 1.0)
    return {
        "elevation": clamp(elevation, 0.0, 1.0),
        "land": land,
        "depth": depth,
        "relief": relief,
        "plate": plate["id"],
        "boundary": boundary,
    }


def climate_at(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> tuple[float, float, float]:
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    nx, ny = x / max(w - 1, 1), y / max(h - 1, 1)
    geo = geography_at(env, plates, x, y, seed)
    season = float(env.get("season_phase", 0.0))
    lat = abs(ny - 0.5) * 2
    temp = float(env.get("temperature", 0.55)) - 0.36 * lat - 0.20 * geo["relief"]
    temp += 0.045 * math.sin(season + nx * math.tau)
    temp += 0.10 * _noise(nx * math.tau, ny * math.tau, seed ^ 0xCC91, 1.2)
    moisture = float(env.get("moisture", 0.53))
    moisture += 0.16 * _noise(nx * math.tau, ny * math.tau, seed ^ 0x7142, 1.0)
    # Coasts are moist; high relief can create rain-shadow variation.
    if geo["land"]:
        moisture += 0.06 * (1.0 - geo["relief"])
        moisture -= 0.07 * geo["relief"] * max(0.0, _noise(nx * 7, ny * 7, seed ^ 0x81, 1.0))
    else:
        moisture += 0.14
    resources = float(env.get("resources", 0.69))
    resources *= 0.52 + 0.48 * clamp(moisture, 0, 1)
    resources *= 0.64 + 0.36 * clamp(1.0 - abs(temp - 0.56) * 1.5, 0, 1)
    if not geo["land"]:
        resources *= 0.75 + 0.22 * (1 - geo["depth"])
    # Ecosystem engineers can locally improve moisture/resource retention.
    gx=int(clamp(x/max(w,1)*GRID_COLS,0,GRID_COLS-1)); gy=int(clamp(y/max(h,1)*GRID_ROWS,0,GRID_ROWS-1))
    for mod in env.get("biotic_modifiers", []):
        if abs(int(mod.get("x",-99))-gx)<=1 and abs(int(mod.get("y",-99))-gy)<=1:
            resources += float(mod.get("strength",0.0))
            moisture += float(mod.get("moisture",0.0))
    # Long-lived disaster scars.
    for scar in env.get("scars", []):
        dx, dy = x - float(scar.get("x", 0)), y - float(scar.get("y", 0))
        radius = max(1.0, float(scar.get("radius", 20)))
        dist = math.hypot(dx, dy)
        if dist >= radius:
            continue
        f = (1 - dist / radius) * float(scar.get("strength", 0.1))
        kind = scar.get("kind", "")
        if kind in {"drought", "fire", "impact", "volcanic"}:
            moisture -= f * (0.85 if kind == "drought" else 0.3)
            resources -= f * (0.55 if kind in {"fire", "impact"} else 0.3)
        if kind in {"cooling", "impact", "volcanic"}:
            temp -= f * (0.45 if kind == "cooling" else 0.18)
        if kind in {"flood", "bloom"}:
            moisture += f * 0.65
            resources += f * 0.5
    return clamp(temp, 0, 1), clamp(moisture, 0, 1), clamp(resources, 0.03, 1.25)


def biome_at(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> str:
    geo = geography_at(env, plates, x, y, seed)
    t, m, r = climate_at(env, plates, x, y, seed)
    if not geo["land"]:
        return "abyss" if geo["depth"] > 0.42 else "shelf"
    if t < 0.13:
        return "ice"
    if geo["relief"] > 0.67:
        return "alpine"
    if t < 0.27:
        return "tundra"
    if m < 0.22:
        return "desert"
    if m < 0.38:
        return "steppe"
    if m > 0.74 and t > 0.58:
        return "rainforest"
    if m > 0.69:
        return "wetland"
    if r < 0.18:
        return "barren"
    return "temperate"


def cell_world_xy(cell: tuple[int, int] | list[int], env: dict[str, Any]) -> tuple[float, float]:
    gx, gy = int(cell[0]), int(cell[1])
    return ((gx + 0.5) * float(env.get("width", 160)) / GRID_COLS,
            (gy + 0.5) * float(env.get("height", 100)) / GRID_ROWS)


def world_to_cell(x: float, y: float, env: dict[str, Any]) -> tuple[int, int]:
    gx = int(clamp(x / max(float(env.get("width", 160)), 1) * GRID_COLS, 0, GRID_COLS - 1))
    gy = int(clamp(y / max(float(env.get("height", 100)), 1) * GRID_ROWS, 0, GRID_ROWS - 1))
    return gx, gy


def neighbors(cell: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = cell
    out = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < GRID_COLS and 0 <= ny < GRID_ROWS:
                out.append((nx, ny))
    return out


def region_name(cell: tuple[int, int]) -> str:
    x, y = cell
    horiz = "western" if x < GRID_COLS / 3 else "eastern" if x >= GRID_COLS * 2 / 3 else "central"
    vert = "northern" if y < GRID_ROWS / 3 else "southern" if y >= GRID_ROWS * 2 / 3 else "midland"
    if horiz == "central" and vert == "midland": return "central reach"
    if horiz == "central": return f"{vert} reach"
    if vert == "midland": return f"{horiz} reach"
    return f"{vert} {horiz} reach"


def _add_scar(env: dict[str, Any], rng: random.Random, generation: int, kind: str, severity: float) -> dict[str, Any]:
    scar = {
        "id": f"scar-{generation:06d}-{rng.randrange(1000,9999)}",
        "kind": kind,
        "generation": generation,
        "x": round(rng.uniform(0, float(env.get("width", 160))), 3),
        "y": round(rng.uniform(0, float(env.get("height", 100))), 3),
        "radius": round(rng.uniform(10, 31) * (0.75 + severity), 3),
        "strength": round(clamp(rng.uniform(0.09, 0.22) * (0.7 + severity), 0.05, 0.65), 4),
        "severity": round(severity, 4),
    }
    env.setdefault("scars", []).append(scar)
    env["scars"] = env["scars"][-MAX_SCARS:]
    return scar


def evolve_planet(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    generation = int(world["generation"])
    events: list[dict[str, Any]] = []
    # Different clocks: ecology every generation, climate slowly, geology extremely slowly.
    clocks = world.setdefault("clocks", {"ecology": 0, "evolution": 0.0, "climate": 0.0, "geology": 0.0})
    clocks["ecology"] = generation
    clocks["evolution"] = round(float(clocks.get("evolution", 0.0)) + 0.18, 4)
    clocks["climate"] = round(float(clocks.get("climate", 0.0)) + 0.035, 4)
    clocks["geology"] = round(float(clocks.get("geology", 0.0)) + 0.006, 6)
    env["season_phase"] = round((float(env.get("season_phase", 0.0)) + 0.33) % math.tau, 6)
    env["temperature"] = round(clamp(float(env.get("temperature", 0.55)) + rng.gauss(0, 0.0024), 0.28, 0.78), 4)
    env["moisture"] = round(clamp(float(env.get("moisture", 0.53)) + rng.gauss(0, 0.0032), 0.24, 0.82), 4)
    env["resources"] = round(clamp(float(env.get("resources", 0.69)) + rng.gauss(0, 0.004), 0.28, 0.95), 4)
    # Slowly decay local scars.
    kept = []
    for scar in env.get("scars", []):
        s = dict(scar)
        s["strength"] = round(float(s.get("strength", 0.1)) * 0.993, 5)
        if s["strength"] > 0.012:
            kept.append(s)
    env["scars"] = kept[-MAX_SCARS:]
    # Plate drift. Centers wrap horizontally and bounce vertically.
    drift_scale = float(plates.get("drift_scale", 0.22))
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    for p in plates.get("plates", []):
        p["cx"] = round((float(p["cx"]) + float(p["vx"]) * drift_scale) % w, 5)
        ny = float(p["cy"]) + float(p["vy"]) * drift_scale
        if ny < 2 or ny > h - 2:
            p["vy"] = round(-float(p["vy"]), 6)
            ny = clamp(ny, 2, h - 2)
        p["cy"] = round(ny, 5)
    plates["geology_clock"] = round(float(plates.get("geology_clock", 0.0)) + drift_scale, 5)
    # Rare tectonic marker when boundary energy peaks by chance.
    if rng.random() < 0.012:
        events.append({"generation": generation, "kind": "tectonic", "subject": "world", "text": "Plate-boundary strain reorganizes part of the crust."})
    # Local disasters. Probabilities are conditions, not scheduled generation numbers.
    roll = rng.random()
    kind = None
    severity = rng.uniform(0.25, 0.8)
    if roll < 0.008:
        kind = "drought"
    elif roll < 0.013:
        kind = "flood"
    elif roll < 0.017:
        kind = "fire"
    elif roll < 0.020:
        kind = "volcanic"
    elif roll < 0.023:
        kind = "cooling"
    elif roll < 0.027:
        kind = "bloom"
    if kind:
        scar = _add_scar(env, rng, generation, kind, severity)
        events.append({
            "generation": generation, "kind": "disaster" if kind != "bloom" else "climate", "subject": "world",
            "text": f"A {kind} event alters the {int(scar['radius'])}-unit region around ({int(scar['x'])}, {int(scar['y'])}).",
            "scar_id": scar["id"], "severity": severity,
        })
    return events

# === PALEON ENGINE OVERRIDE v2 START ===
# DEEP TIME 2.0 keeps planet.py as PHYLUM's compatibility surface while the
# coupled planetary model lives in paleon.py. Import-time rebinding means
# biology.py and render.py automatically receive the PALEON implementations.
from .paleon import (
    evolve_paleon_planet as evolve_planet,
    paleon_biome_at as biome_at,
    paleon_climate_at as climate_at,
    paleon_geography_at as geography_at,
)
# === PALEON ENGINE OVERRIDE v2 END ===
