from __future__ import annotations

import html
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable

from .constants import GRID_COLS, GRID_ROWS, MAX_SCARS
from .utils import clamp, mean, stable_int

PALEON_SCHEMA_VERSION = 2
COARSE_COLS = 24
COARSE_ROWS = 15


def _noise(x: float, y: float, seed: int, scale: float = 1.0) -> float:
    """Cheap deterministic multi-frequency field in approximately -1..1."""
    p = (seed % 104729) / 104729.0 * math.tau
    return (
        0.43 * math.sin((x * 1.23 + y * 0.71) * scale + p)
        + 0.29 * math.cos((x * 0.47 - y * 1.51) * scale - p * 0.61)
        + 0.19 * math.sin((x * 2.71 + y * 2.07) * scale + p * 1.27)
        + 0.09 * math.cos((x * 5.19 - y * 3.33) * scale + p * 0.23)
    )


def _rng(seed: int, *parts: object) -> random.Random:
    key = ":".join(str(x) for x in parts)
    return random.Random((seed ^ stable_int(key)) & ((1 << 63) - 1))


def _coarse_index(x: float, y: float, env: dict[str, Any]) -> int:
    w = max(1.0, float(env.get("width", 160)))
    h = max(1.0, float(env.get("height", 100)))
    gx = int(clamp(x / w * COARSE_COLS, 0, COARSE_COLS - 1))
    gy = int(clamp(y / h * COARSE_ROWS, 0, COARSE_ROWS - 1))
    return gy * COARSE_COLS + gx


def _coarse_value(env: dict[str, Any], key: str, x: float, y: float, default: float) -> float:
    p = env.get("paleon", {})
    coarse = p.get("surface", {})
    values = coarse.get(key, [])
    idx = _coarse_index(x, y, env)
    if isinstance(values, list) and idx < len(values):
        try:
            return float(values[idx])
        except (TypeError, ValueError):
            pass
    return default


def _set_coarse(env: dict[str, Any], key: str, idx: int, value: float) -> None:
    surface = env.setdefault("paleon", {}).setdefault("surface", {})
    arr = surface.setdefault(key, [0.0] * (COARSE_COLS * COARSE_ROWS))
    if len(arr) < COARSE_COLS * COARSE_ROWS:
        arr.extend([0.0] * (COARSE_COLS * COARSE_ROWS - len(arr)))
    arr[idx] = round(float(value), 5)


def _distance_x(a: float, b: float, width: float) -> float:
    d = a - b
    if width <= 0:
        return d
    if d > width / 2:
        d -= width
    elif d < -width / 2:
        d += width
    return d


def _plate_at(plates: dict[str, Any], x: float, y: float, env: dict[str, Any]) -> dict[str, Any]:
    plist = plates.get("plates", [])
    if not plist:
        return {
            "id": "plate-00", "cx": 0.0, "cy": 0.0, "vx": 0.0, "vy": 0.0,
            "continental": True, "buoyancy": 0.0, "crust_age": 0.5,
            "thickness": 0.5, "heat_flux": 0.2, "stress": 0.0,
        }
    width = float(env.get("width", 160))
    def d2(p: dict[str, Any]) -> float:
        dx = _distance_x(x, float(p.get("cx", 0)), width)
        dy = y - float(p.get("cy", 0))
        return dx * dx + dy * dy
    return min(plist, key=d2)


def _boundary_state(plates: dict[str, Any], x: float, y: float, env: dict[str, Any]) -> dict[str, Any]:
    plist = plates.get("plates", [])
    if len(plist) < 2:
        p = _plate_at(plates, x, y, env)
        return {"strength": 0.0, "kind": "interior", "convergence": 0.0, "shear": 0.0, "a": p, "b": p}
    width = float(env.get("width", 160))
    rows: list[tuple[float, dict[str, Any]]] = []
    for p in plist:
        dx = _distance_x(x, float(p.get("cx", 0)), width)
        dy = y - float(p.get("cy", 0))
        rows.append((math.hypot(dx, dy), p))
    rows.sort(key=lambda z: z[0])
    d0, a = rows[0]
    d1, b = rows[1]
    gap = max(0.0, d1 - d0)
    strength = clamp(1.0 - gap / 13.0, 0.0, 1.0)
    ax, ay = float(a.get("cx", 0)), float(a.get("cy", 0))
    bx, by = float(b.get("cx", 0)), float(b.get("cy", 0))
    nx = _distance_x(bx, ax, width)
    ny = by - ay
    mag = math.hypot(nx, ny) or 1.0
    nx, ny = nx / mag, ny / mag
    rvx = float(b.get("vx", 0)) - float(a.get("vx", 0))
    rvy = float(b.get("vy", 0)) - float(a.get("vy", 0))
    normal = rvx * nx + rvy * ny
    tangent = rvx * (-ny) + rvy * nx
    convergence = clamp(-normal / 0.085, -1.0, 1.0)
    shear = clamp(abs(tangent) / 0.085, 0.0, 1.0)
    if convergence > 0.18:
        kind = "convergent"
    elif convergence < -0.18:
        kind = "divergent"
    elif shear > 0.18:
        kind = "transform"
    else:
        kind = "passive"
    return {"strength": strength, "kind": kind, "convergence": convergence, "shear": shear, "a": a, "b": b}


def _initialize_plate_properties(seed: int, plates: dict[str, Any]) -> None:
    for i, p in enumerate(plates.get("plates", [])):
        r = _rng(seed, "paleon", "plate", p.get("id", i))
        p.setdefault("crust_type", "continental" if p.get("continental", False) else "oceanic")
        p.setdefault("crust_age", round(r.uniform(0.08, 0.88), 4))
        p.setdefault("thickness", round(r.uniform(0.44, 0.88) if p.get("continental") else r.uniform(0.18, 0.48), 4))
        p.setdefault("heat_flux", round(r.uniform(0.12, 0.48), 4))
        p.setdefault("stress", round(r.uniform(0.02, 0.13), 4))
        p.setdefault("erosion", round(r.uniform(0.04, 0.18), 4))
        p.setdefault("volcanism", round(r.uniform(0.03, 0.15), 4))


def _initial_surface(seed: int) -> dict[str, list[float]]:
    soil: list[float] = []
    soil_carbon: list[float] = []
    freshwater: list[float] = []
    disturbance: list[float] = []
    succession: list[float] = []
    sediment: list[float] = []
    for gy in range(COARSE_ROWS):
        for gx in range(COARSE_COLS):
            nx = (gx + 0.5) / COARSE_COLS
            ny = (gy + 0.5) / COARSE_ROWS
            n = _noise(nx * math.tau, ny * math.tau, seed ^ 0x50A1, 1.0)
            wet = clamp(0.52 + 0.22 * _noise(nx * 5.1, ny * 5.1, seed ^ 0xB811, 1.0), 0.05, 0.95)
            f = clamp(0.48 + 0.20 * n + 0.10 * wet, 0.08, 0.92)
            soil.append(round(f, 4))
            soil_carbon.append(round(clamp(f * 0.52 + 0.08 * (1 - abs(ny - 0.5) * 2), 0.03, 0.75), 4))
            freshwater.append(round(wet, 4))
            disturbance.append(0.0)
            succession.append(round(clamp(0.42 + f * 0.42, 0.08, 0.92), 4))
            sediment.append(round(clamp(0.20 + 0.20 * wet + 0.09 * n, 0.02, 0.65), 4))
    return {
        "soil_fertility": soil,
        "soil_carbon": soil_carbon,
        "freshwater": freshwater,
        "disturbance": disturbance,
        "succession": succession,
        "sediment": sediment,
    }


def ensure_paleon_state(
    world: dict[str, Any],
    env: dict[str, Any],
    plates: dict[str, Any],
    species: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Migrate an existing DEEP TIME world into PALEON without consuming a generation."""
    seed = int(world.get("seed", 314159265))
    _initialize_plate_properties(seed, plates)
    p = env.setdefault("paleon", {})
    p.setdefault("schema", PALEON_SCHEMA_VERSION)
    p["schema"] = PALEON_SCHEMA_VERSION
    p.setdefault("installed_generation", int(world.get("generation", 0)))
    p.setdefault("atmosphere", {
        "co2": 0.00042,
        "oxygen": 0.209,
        "methane": 0.0000019,
        "aerosols": 0.012,
        "pressure": 1.0,
        "greenhouse_index": 0.0,
    })
    p.setdefault("ocean", {
        "heat": clamp(float(env.get("temperature", 0.55)) * 0.82 + 0.08, 0.05, 0.95),
        "oxygen": 0.72,
        "nutrients": 0.61,
        "acidity": 0.30,
        "circulation": 0.66,
        "anoxia": 0.0,
        "current_phase": 0.0,
    })
    p.setdefault("cryosphere", {
        "ice_fraction": clamp(0.12 + (0.52 - float(env.get("temperature", 0.55))) * 0.34, 0.01, 0.42),
        "snowline": 0.77,
        "sea_level_anomaly": 0.0,
    })
    p.setdefault("cycles", {
        "living_carbon": 0.48,
        "soil_carbon": 0.52,
        "ocean_carbon": 0.64,
        "available_nitrogen": 0.56,
        "available_phosphorus": 0.47,
        "decomposition": 0.42,
    })
    p.setdefault("hydrology", {
        "global_freshwater": clamp(float(env.get("moisture", 0.53)), 0.05, 0.95),
        "runoff": 0.43,
        "evaporation": 0.46,
        "storminess": 0.26,
        "flood_index": 0.0,
        "drought_index": 0.0,
    })
    p.setdefault("weather", {
        "enso_like": 0.0,
        "storm_phase": 0.0,
        "heat_extreme": 0.0,
        "cold_extreme": 0.0,
    })
    if not isinstance(p.get("surface"), dict) or len(p.get("surface", {}).get("soil_fertility", [])) != COARSE_COLS * COARSE_ROWS:
        p["surface"] = _initial_surface(seed)
    p.setdefault("history", [])
    p.setdefault("tipping", {"ocean_anoxia": False, "icehouse": False, "greenhouse": False})
    plates.setdefault("sea_level", 0.47)
    plates.setdefault("paleon_schema", PALEON_SCHEMA_VERSION)
    plates["paleon_schema"] = PALEON_SCHEMA_VERSION
    return p


def _greenhouse_forcing(atm: dict[str, Any]) -> float:
    co2 = max(0.00008, float(atm.get("co2", 0.00042)))
    methane = max(0.0000001, float(atm.get("methane", 0.0000019)))
    aerosols = clamp(float(atm.get("aerosols", 0.0)), 0.0, 1.0)
    co2_forcing = math.log(co2 / 0.00042, 2) * 0.026
    methane_forcing = math.log(methane / 0.0000019, 2) * 0.010
    return clamp(co2_forcing + methane_forcing - aerosols * 0.19, -0.18, 0.22)


def paleon_geography_at(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> dict[str, Any]:
    # Plate dictionaries may be created independently against an environment that
    # has already been migrated to PALEON. Initialize each plate instance itself
    # before reading tectonic properties so identical seeds remain deterministic.
    _initialize_plate_properties(seed, plates)
    if int(env.get("paleon", {}).get("schema", 0)) != PALEON_SCHEMA_VERSION:
        ensure_paleon_state({"seed": seed, "generation": 0}, env, plates, None)
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    nx, ny = x / max(w, 1), y / max(h, 1)
    plate = _plate_at(plates, x, y, env)
    boundary = _boundary_state(plates, x, y, env)
    drift = float(plates.get("geology_clock", 0.0))
    phase = float(plate.get("phase", 0.0))
    base = 0.49 + 0.22 * _noise(nx * math.tau + drift * 0.00055, ny * math.tau, seed ^ 0x917A, 1.0)
    detail = 0.075 * _noise(nx * math.tau * 3.2, ny * math.tau * 3.2, seed ^ 0xA51C, 1.0)
    micro = 0.025 * _noise(nx * 17 + phase, ny * 17 - phase, seed ^ 0xE301, 1.0)
    continental = str(plate.get("crust_type", "continental")) == "continental"
    plate_bias = float(plate.get("buoyancy", 0.0)) + (0.066 if continental else -0.082)
    bstrength = float(boundary["strength"])
    convergence = float(boundary["convergence"])
    shear = float(boundary["shear"])
    uplift = bstrength * max(0.0, convergence) * (0.12 + 0.08 * float(plate.get("thickness", 0.5)))
    rift = bstrength * max(0.0, -convergence) * 0.075
    transform_relief = bstrength * shear * 0.026
    erosion = float(plate.get("erosion", 0.1)) * max(0.0, base - 0.56) * 0.05
    elevation = base + detail + micro + plate_bias + uplift + transform_relief - rift - erosion
    for refuge in env.get("ancestral_refugia", []):
        dx = _distance_x(x, float(refuge.get("x", 0)), w)
        dy = y - float(refuge.get("y", 0))
        radius = max(1.0, float(refuge.get("radius", 11)))
        d = math.hypot(dx, dy)
        if d < radius:
            elevation += 0.11 * (1 - d / radius)
    paleon = env.get("paleon", {})
    cryo = paleon.get("cryosphere", {})
    sea = float(plates.get("sea_level", 0.47)) + float(cryo.get("sea_level_anomaly", 0.0))
    sea = clamp(sea, 0.39, 0.57)
    land = elevation >= sea
    depth = clamp((sea - elevation) / 0.34, 0.0, 1.0)
    relief = clamp((elevation - sea) / 0.39, 0.0, 1.0)
    soil = _coarse_value(env, "soil_fertility", x, y, 0.48)
    freshwater = _coarse_value(env, "freshwater", x, y, 0.48)
    succession = _coarse_value(env, "succession", x, y, 0.50)
    disturbance = _coarse_value(env, "disturbance", x, y, 0.0)
    return {
        "elevation": clamp(elevation, 0.0, 1.0),
        "land": land,
        "depth": depth,
        "relief": relief,
        "plate": plate.get("id", "plate-00"),
        "boundary": bstrength,
        "boundary_type": boundary["kind"],
        "convergence": convergence,
        "shear": shear,
        "tectonic_stress": clamp(float(plate.get("stress", 0.0)) + bstrength * (abs(convergence) + shear) * 0.35, 0, 1),
        "soil": soil,
        "freshwater": freshwater,
        "succession": succession,
        "disturbance": disturbance,
        "sea_level": sea,
    }


def _ocean_proximity(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> float:
    geo = paleon_geography_at(env, plates, x, y, seed)
    if not geo["land"]:
        return 1.0
    w = float(env.get("width", 160)); h = float(env.get("height", 100))
    water = 0
    samples = 0
    for r in (7.0, 16.0):
        for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
            xx = (x + dx) % w
            yy = clamp(y + dy, 0, h)
            if not paleon_geography_at(env, plates, xx, yy, seed)["land"]:
                water += 1
            samples += 1
    return water / max(1, samples)


def _scar_effects(env: dict[str, Any], x: float, y: float) -> tuple[float, float, float]:
    dt = dm = dr = 0.0
    for scar in env.get("scars", []):
        dx = x - float(scar.get("x", 0)); dy = y - float(scar.get("y", 0))
        radius = max(1.0, float(scar.get("radius", 20)))
        d = math.hypot(dx, dy)
        if d >= radius:
            continue
        f = (1 - d / radius) * float(scar.get("strength", 0.1))
        kind = str(scar.get("kind", ""))
        if kind == "drought": dm -= f * 0.85; dr -= f * 0.38; dt += f * 0.08
        elif kind == "fire": dm -= f * 0.22; dr -= f * 0.48; dt += f * 0.04
        elif kind == "impact": dm -= f * 0.24; dr -= f * 0.62; dt -= f * 0.17
        elif kind == "volcanic": dm -= f * 0.08; dr -= f * 0.28; dt -= f * 0.15
        elif kind == "cooling": dt -= f * 0.46
        elif kind == "flood": dm += f * 0.72; dr += f * 0.20
        elif kind == "bloom": dm += f * 0.12; dr += f * 0.56
        elif kind == "storm": dm += f * 0.28; dr -= f * 0.12
        elif kind == "glaciation": dt -= f * 0.30; dm -= f * 0.18
        elif kind == "anoxia": dr -= f * 0.55
    return dt, dm, dr


def _climate_raw(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> tuple[float, float, float]:
    p = env.get("paleon", {})
    atm = p.get("atmosphere", {})
    ocean = p.get("ocean", {})
    hydro = p.get("hydrology", {})
    weather = p.get("weather", {})
    geo = paleon_geography_at(env, plates, x, y, seed)
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    nx, ny = x / max(w, 1), y / max(h, 1)
    latitude = abs(ny - 0.5) * 2.0
    season = float(env.get("season_phase", 0.0))
    hemi = 1.0 if ny < 0.5 else -1.0
    seasonal = math.sin(season) * hemi * (0.028 + latitude * 0.065)
    forcing = _greenhouse_forcing(atm)
    oceanity = _ocean_proximity(env, plates, x, y, seed)
    ocean_heat = float(ocean.get("heat", env.get("temperature", 0.55)))
    base_global = float(env.get("temperature", 0.55))
    temp = base_global - 0.37 * latitude - 0.22 * geo["relief"] + forcing + seasonal
    temp += oceanity * (ocean_heat - temp) * 0.22
    temp += 0.065 * _noise(nx * math.tau, ny * math.tau, seed ^ 0xCC91, 1.25)
    # Three-cell atmospheric oscillation resembling a shifting ocean-atmosphere mode.
    temp += float(weather.get("enso_like", 0.0)) * math.sin(nx * math.tau) * 0.025

    freshwater = geo["freshwater"]
    moisture = float(env.get("moisture", 0.53))
    moisture += 0.14 * _noise(nx * math.tau, ny * math.tau, seed ^ 0x7142, 1.0)
    moisture += oceanity * 0.18 + freshwater * 0.11
    moisture += float(hydro.get("global_freshwater", 0.53) - 0.53) * 0.35
    # Prevailing wind belts reverse direction with latitude; uplift dries the lee side.
    wind_sign = 1.0 if latitude < 0.35 else -1.0 if latitude < 0.72 else 1.0
    rain_wave = _noise(nx * 9.0 + wind_sign * 0.9, ny * 7.0, seed ^ 0x8811, 1.0)
    moisture += rain_wave * 0.055
    if geo["land"]:
        moisture -= geo["relief"] * 0.085 * max(0.0, rain_wave)
        moisture -= geo["disturbance"] * 0.06
    else:
        moisture += 0.12

    light = clamp(1.02 - latitude * 0.34 - max(0.0, float(atm.get("aerosols", 0.0)) - 0.02) * 0.55, 0.25, 1.0)
    temp_fit = clamp(1.0 - abs(temp - 0.56) * 1.65, 0.0, 1.0)
    water_fit = clamp(moisture, 0.0, 1.0)
    soil = geo["soil"]
    succession = geo["succession"]
    nutrient = mean([
        float(p.get("cycles", {}).get("available_nitrogen", 0.56)),
        float(p.get("cycles", {}).get("available_phosphorus", 0.47)),
        soil,
    ])
    if geo["land"]:
        resources = (light ** 0.38) * (temp_fit ** 0.55) * (water_fit ** 0.72) * (0.42 + nutrient * 0.58)
        resources *= 0.58 + succession * 0.42
    else:
        upwelling = 0.55 + 0.35 * geo["boundary"] + 0.22 * (1 - geo["depth"])
        resources = light * (0.35 + float(ocean.get("nutrients", 0.6)) * 0.65) * upwelling
        resources *= 0.40 + float(ocean.get("oxygen", 0.7)) * 0.60
        resources *= 1.0 - float(ocean.get("anoxia", 0.0)) * 0.72

    # Existing ecosystem engineers remain part of the local feedback loop.
    gx = int(clamp(x / max(w, 1) * GRID_COLS, 0, GRID_COLS - 1))
    gy = int(clamp(y / max(h, 1) * GRID_ROWS, 0, GRID_ROWS - 1))
    for mod in env.get("biotic_modifiers", []):
        if abs(int(mod.get("x", -99)) - gx) <= 1 and abs(int(mod.get("y", -99)) - gy) <= 1:
            resources += float(mod.get("strength", 0.0))
            moisture += float(mod.get("moisture", 0.0))

    dt, dm, dr = _scar_effects(env, x, y)
    temp += dt; moisture += dm; resources += dr
    return clamp(temp, 0.0, 1.0), clamp(moisture, 0.0, 1.0), clamp(resources, 0.025, 1.35)


def paleon_climate_at(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> tuple[float, float, float]:
    return _climate_raw(env, plates, x, y, seed)


def paleon_biome_at(env: dict[str, Any], plates: dict[str, Any], x: float, y: float, seed: int) -> str:
    geo = paleon_geography_at(env, plates, x, y, seed)
    t, m, r = paleon_climate_at(env, plates, x, y, seed)
    cryo = env.get("paleon", {}).get("cryosphere", {})
    if not geo["land"]:
        return "abyss" if geo["depth"] > 0.42 else "shelf"
    if t < 0.13 or (abs(y / max(float(env.get("height", 100)), 1) - 0.5) > 0.43 and float(cryo.get("ice_fraction", 0.1)) > 0.20):
        return "ice"
    if geo["relief"] > 0.69:
        return "alpine"
    if t < 0.27:
        return "tundra"
    if m < 0.21:
        return "desert"
    if m < 0.39:
        return "steppe"
    if m > 0.73 and t > 0.57 and r > 0.45:
        return "rainforest"
    if m > 0.68 or geo["freshwater"] > 0.79:
        return "wetland"
    if r < 0.18 or geo["disturbance"] > 0.72:
        return "barren"
    return "temperate"


def _add_scar(env: dict[str, Any], rng: random.Random, generation: int, kind: str, severity: float) -> dict[str, Any]:
    scar = {
        "id": f"scar-{generation:06d}-{rng.randrange(1000, 9999)}",
        "kind": kind,
        "generation": generation,
        "x": round(rng.uniform(0, float(env.get("width", 160))), 3),
        "y": round(rng.uniform(0, float(env.get("height", 100))), 3),
        "radius": round(rng.uniform(9, 30) * (0.72 + severity), 3),
        "strength": round(clamp(rng.uniform(0.08, 0.21) * (0.72 + severity), 0.04, 0.68), 4),
        "severity": round(severity, 4),
    }
    env.setdefault("scars", []).append(scar)
    env["scars"] = env["scars"][-MAX_SCARS:]
    return scar


def _update_plate_dynamics(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    generation = int(world.get("generation", 0))
    pstate = env["paleon"]
    drift_scale = float(plates.get("drift_scale", 0.22))
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    for p in plates.get("plates", []):
        p["cx"] = round((float(p.get("cx", 0)) + float(p.get("vx", 0)) * drift_scale) % w, 5)
        ny = float(p.get("cy", 0)) + float(p.get("vy", 0)) * drift_scale
        if ny < 2 or ny > h - 2:
            p["vy"] = round(-float(p.get("vy", 0)), 6)
            ny = clamp(ny, 2, h - 2)
        p["cy"] = round(ny, 5)
        # Crust ages and cools except at young oceanic rifts; stress slowly accumulates.
        p["crust_age"] = round(clamp(float(p.get("crust_age", 0.4)) + (0.00016 if p.get("crust_type") == "oceanic" else 0.00005), 0.01, 1.0), 5)
        p["heat_flux"] = round(clamp(float(p.get("heat_flux", 0.2)) * 0.9994 + (1 - float(p.get("crust_age", 0.4))) * 0.0005, 0.03, 0.8), 5)
        p["stress"] = round(clamp(float(p.get("stress", 0.05)) * 0.994 + rng.uniform(0.0005, 0.004), 0.0, 1.0), 5)
    plates["geology_clock"] = round(float(plates.get("geology_clock", 0.0)) + drift_scale, 5)

    # Sample boundary mechanics and convert prolonged stress into unscripted tectonic events.
    samples: list[tuple[float, dict[str, Any], float, float]] = []
    for _ in range(24):
        x = rng.uniform(0, w); y = rng.uniform(0, h)
        b = _boundary_state(plates, x, y, env)
        score = b["strength"] * (abs(b["convergence"]) + b["shear"] * 0.7)
        samples.append((score, b, x, y))
    score, boundary, x, y = max(samples, key=lambda z: z[0])
    a = boundary["a"]; b = boundary["b"]
    accumulated = mean([float(a.get("stress", 0)), float(b.get("stress", 0))])
    trigger = score * (0.35 + accumulated)
    if trigger > 0.46 and rng.random() < 0.035 + trigger * 0.035:
        kind = boundary["kind"]
        text = {
            "convergent": "Convergent plate strain builds new relief along a collision belt.",
            "divergent": "A rift opens as plates pull apart and young crust is exposed.",
            "transform": "A transform boundary releases accumulated shear strain.",
        }.get(kind, "Plate-boundary strain reorganizes part of the crust.")
        events.append({"generation": generation, "kind": "tectonic", "subject": "world", "text": text, "boundary_type": kind, "x": round(x, 2), "y": round(y, 2), "severity": round(trigger, 4)})
        a["stress"] = round(float(a.get("stress", 0)) * 0.46, 5)
        b["stress"] = round(float(b.get("stress", 0)) * 0.46, 5)
        if kind == "divergent":
            for plate in (a, b):
                if plate.get("crust_type") == "oceanic":
                    plate["crust_age"] = round(max(0.02, float(plate.get("crust_age", 0.4)) - 0.04), 5)
                    plate["heat_flux"] = round(clamp(float(plate.get("heat_flux", 0.2)) + 0.045, 0, 1), 5)
        if kind == "convergent" and rng.random() < 0.45:
            scar = _add_scar(env, rng, generation, "volcanic", clamp(trigger, 0.2, 0.9))
            scar["x"] = round(x, 3); scar["y"] = round(y, 3)
            pstate["atmosphere"]["aerosols"] = round(clamp(float(pstate["atmosphere"].get("aerosols", 0)) + trigger * 0.025, 0, 0.45), 6)
    return events


def _update_surface(world: dict[str, Any], env: dict[str, Any], rng: random.Random) -> None:
    p = env["paleon"]
    surface = p["surface"]
    scars = env.get("scars", [])
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    for gy in range(COARSE_ROWS):
        for gx in range(COARSE_COLS):
            idx = gy * COARSE_COLS + gx
            x = (gx + 0.5) / COARSE_COLS * w
            y = (gy + 0.5) / COARSE_ROWS * h
            disturbance = float(surface["disturbance"][idx]) * 0.965
            for scar in scars[-20:]:
                dx = _distance_x(x, float(scar.get("x", 0)), w); dy = y - float(scar.get("y", 0))
                radius = max(1.0, float(scar.get("radius", 20)))
                d = math.hypot(dx, dy)
                if d < radius:
                    disturbance = max(disturbance, (1 - d / radius) * float(scar.get("strength", 0.1)) * 1.45)
            succession = float(surface["succession"][idx])
            succession += (1.0 - disturbance - succession) * 0.018
            succession -= disturbance * 0.022
            soil = float(surface["soil_fertility"][idx])
            soil_c = float(surface["soil_carbon"][idx])
            freshwater = float(surface["freshwater"][idx])
            sediment = float(surface["sediment"][idx])
            soil += (succession * 0.54 + soil_c * 0.28 - soil) * 0.008 - disturbance * 0.003
            soil_c += (succession * 0.62 - soil_c) * 0.006 - disturbance * 0.005
            freshwater += (float(p["hydrology"].get("global_freshwater", 0.53)) - freshwater) * 0.009
            freshwater += rng.gauss(0, 0.0015)
            sediment += disturbance * 0.004 + float(p["hydrology"].get("runoff", 0.4)) * 0.0007 - sediment * 0.0006
            surface["disturbance"][idx] = round(clamp(disturbance, 0, 1), 5)
            surface["succession"][idx] = round(clamp(succession, 0.02, 1), 5)
            surface["soil_fertility"][idx] = round(clamp(soil, 0.02, 1), 5)
            surface["soil_carbon"][idx] = round(clamp(soil_c, 0.01, 1), 5)
            surface["freshwater"][idx] = round(clamp(freshwater, 0.02, 1), 5)
            surface["sediment"][idx] = round(clamp(sediment, 0.01, 1), 5)


def _update_global_climate(world: dict[str, Any], env: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    p = env["paleon"]
    atm = p["atmosphere"]; ocean = p["ocean"]; cryo = p["cryosphere"]; hydro = p["hydrology"]; weather = p["weather"]
    generation = int(world.get("generation", 0))
    events: list[dict[str, Any]] = []
    forcing = _greenhouse_forcing(atm)
    atm["greenhouse_index"] = round(forcing, 6)
    target_temp = clamp(0.55 + forcing - float(atm.get("aerosols", 0)) * 0.06 + (float(ocean.get("heat", 0.53)) - 0.53) * 0.12, 0.18, 0.86)
    env["temperature"] = round(clamp(float(env.get("temperature", 0.55)) * 0.988 + target_temp * 0.012 + rng.gauss(0, 0.0012), 0.20, 0.86), 5)
    ocean["heat"] = round(clamp(float(ocean.get("heat", 0.53)) * 0.994 + float(env["temperature"]) * 0.006, 0.05, 0.92), 5)
    ice_target = clamp((0.49 - float(env["temperature"])) * 0.88 + 0.11, 0.005, 0.55)
    cryo["ice_fraction"] = round(clamp(float(cryo.get("ice_fraction", 0.1)) * 0.989 + ice_target * 0.011, 0.002, 0.58), 5)
    thermal = (float(ocean.get("heat", 0.53)) - 0.53) * 0.055
    ice = (0.12 - float(cryo.get("ice_fraction", 0.12))) * 0.095
    cryo["sea_level_anomaly"] = round(clamp(thermal + ice, -0.055, 0.065), 6)
    cryo["snowline"] = round(clamp(0.72 + (float(env["temperature"]) - 0.5) * 0.30, 0.55, 0.90), 5)

    weather["enso_like"] = round(clamp(float(weather.get("enso_like", 0)) * 0.94 + rng.gauss(0, 0.035), -0.55, 0.55), 5)
    weather["storm_phase"] = round((float(weather.get("storm_phase", 0)) + 0.23 + rng.uniform(-0.02, 0.02)) % math.tau, 6)
    storminess = clamp(0.20 + abs(float(weather["enso_like"])) * 0.25 + max(0, float(ocean["heat"]) - 0.55) * 0.70, 0.08, 0.72)
    hydro["storminess"] = round(storminess, 5)
    evap = clamp(0.36 + float(env["temperature"]) * 0.24 + storminess * 0.06, 0.15, 0.78)
    runoff = clamp(float(env.get("moisture", 0.53)) * 0.55 + storminess * 0.18 + float(cryo.get("ice_fraction", 0.1)) * 0.05, 0.08, 0.86)
    hydro["evaporation"] = round(evap, 5); hydro["runoff"] = round(runoff, 5)
    fresh_target = clamp(float(env.get("moisture", 0.53)) + runoff * 0.12 - evap * 0.09, 0.1, 0.9)
    hydro["global_freshwater"] = round(clamp(float(hydro.get("global_freshwater", 0.53)) * 0.982 + fresh_target * 0.018, 0.08, 0.92), 5)
    env["moisture"] = round(clamp(float(env.get("moisture", 0.53)) * 0.991 + float(hydro["global_freshwater"]) * 0.009 + rng.gauss(0, 0.0011), 0.12, 0.90), 5)

    # Extreme weather emerges from state rather than generation milestones.
    heat_index = clamp((float(env["temperature"]) - 0.61) * 3.2 + rng.random() * 0.15, 0, 1)
    cold_index = clamp((0.39 - float(env["temperature"])) * 3.0 + rng.random() * 0.10, 0, 1)
    drought_index = clamp((0.37 - float(hydro["global_freshwater"])) * 2.6 + heat_index * 0.25, 0, 1)
    flood_index = clamp((float(hydro["global_freshwater"]) - 0.68) * 2.4 + storminess * 0.38, 0, 1)
    weather["heat_extreme"] = round(heat_index, 4); weather["cold_extreme"] = round(cold_index, 4)
    hydro["drought_index"] = round(drought_index, 4); hydro["flood_index"] = round(flood_index, 4)
    checks = [
        ("drought", drought_index, 0.018),
        ("flood", flood_index, 0.016),
        ("storm", storminess, 0.010),
        ("cooling", cold_index, 0.012),
    ]
    for kind, index, base in checks:
        if index > 0.34 and rng.random() < base * (0.5 + index * 1.8):
            scar = _add_scar(env, rng, generation, kind, clamp(index, 0.25, 0.9))
            events.append({"generation": generation, "kind": "disaster" if kind != "cooling" else "climate", "subject": "world", "text": f"A {kind} episode reorganizes habitat across a {int(scar['radius'])}-unit region.", "scar_id": scar["id"], "severity": round(index, 4)})
            break
    return events


def _update_ocean_and_cycles(world: dict[str, Any], env: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    p = env["paleon"]
    atm = p["atmosphere"]; ocean = p["ocean"]; cycles = p["cycles"]; hydro = p["hydrology"]
    generation = int(world.get("generation", 0))
    events: list[dict[str, Any]] = []
    ocean["current_phase"] = round((float(ocean.get("current_phase", 0)) + 0.045 + rng.uniform(-0.004, 0.004)) % math.tau, 6)
    circulation_target = clamp(0.72 - abs(float(ocean.get("heat", 0.53)) - 0.53) * 0.62 - float(hydro.get("storminess", 0.2)) * 0.08, 0.22, 0.86)
    ocean["circulation"] = round(float(ocean.get("circulation", 0.66)) * 0.992 + circulation_target * 0.008, 5)
    nutrient_target = clamp(float(cycles.get("available_nitrogen", 0.56)) * 0.48 + float(cycles.get("available_phosphorus", 0.47)) * 0.34 + (1 - float(ocean["circulation"])) * 0.12, 0.12, 0.88)
    ocean["nutrients"] = round(clamp(float(ocean.get("nutrients", 0.61)) * 0.988 + nutrient_target * 0.012, 0.08, 0.92), 5)
    oxygen_target = clamp(0.78 - max(0.0, float(ocean["heat"]) - 0.52) * 0.72 - float(ocean["nutrients"]) * 0.12 + float(ocean["circulation"]) * 0.16, 0.12, 0.92)
    ocean["oxygen"] = round(clamp(float(ocean.get("oxygen", 0.72)) * 0.987 + oxygen_target * 0.013, 0.08, 0.95), 5)
    anoxia_target = clamp((0.48 - float(ocean["oxygen"])) * 2.2 + max(0, float(ocean["nutrients"]) - 0.72) * 0.8, 0, 1)
    ocean["anoxia"] = round(clamp(float(ocean.get("anoxia", 0)) * 0.975 + anoxia_target * 0.025, 0, 1), 5)
    ocean["acidity"] = round(clamp(0.30 + math.log(max(0.00008, float(atm.get("co2", 0.00042))) / 0.00042, 2) * 0.035, 0.08, 0.72), 5)
    tipping = p["tipping"]
    if float(ocean["anoxia"]) > 0.34 and not bool(tipping.get("ocean_anoxia")):
        tipping["ocean_anoxia"] = True
        events.append({"generation": generation, "kind": "climate", "subject": "world", "text": "Marine oxygen loss crosses into a persistent anoxic interval.", "severity": round(float(ocean["anoxia"]), 4)})
    elif float(ocean["anoxia"]) < 0.16 and bool(tipping.get("ocean_anoxia")):
        tipping["ocean_anoxia"] = False
        events.append({"generation": generation, "kind": "climate", "subject": "world", "text": "Ocean circulation restores oxygen to formerly anoxic waters."})
    return events


def evolve_paleon_planet(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    """The pre-biology half of one PALEON generation: climate, hydrology and geology."""
    ensure_paleon_state(world, env, plates, None)
    generation = int(world.get("generation", 0))
    clocks = world.setdefault("clocks", {"ecology": generation, "evolution": 0.0, "climate": 0.0, "geology": 0.0})
    clocks["ecology"] = generation
    clocks["evolution"] = round(float(clocks.get("evolution", 0.0)) + 0.18, 4)
    clocks["climate"] = round(float(clocks.get("climate", 0.0)) + 0.035, 4)
    clocks["geology"] = round(float(clocks.get("geology", 0.0)) + 0.006, 6)
    env["season_phase"] = round((float(env.get("season_phase", 0.0)) + 0.33) % math.tau, 6)
    p = env["paleon"]
    p["atmosphere"]["aerosols"] = round(clamp(float(p["atmosphere"].get("aerosols", 0.0)) * 0.973, 0, 1), 7)
    # Scars heal on different timescales instead of one universal decay constant.
    rates = {"impact": 0.997, "volcanic": 0.989, "glaciation": 0.996, "fire": 0.965, "flood": 0.972, "storm": 0.91, "drought": 0.978, "cooling": 0.982, "bloom": 0.95, "anoxia": 0.992}
    kept = []
    for scar in env.get("scars", []):
        s = dict(scar)
        s["strength"] = round(float(s.get("strength", 0.1)) * rates.get(str(s.get("kind", "")), 0.987), 6)
        if s["strength"] > 0.010:
            kept.append(s)
    env["scars"] = kept[-MAX_SCARS:]
    events: list[dict[str, Any]] = []
    events.extend(_update_plate_dynamics(world, env, plates, rng))
    events.extend(_update_global_climate(world, env, rng))
    events.extend(_update_ocean_and_cycles(world, env, rng))
    _update_surface(world, env, rng)
    return events


def _species_biomass(sp: dict[str, Any]) -> float:
    pop = max(0.0, float(sp.get("population", 0)))
    g = sp.get("genome", {})
    body = max(0.05, float(g.get("body_size", sp.get("traits", {}).get("body_size", 0.7))))
    soma = sp.get("soma", {})
    metabolism = float(soma.get("physiology", {}).get("metabolism", 0.5))
    return pop * (body ** 0.72) * (0.72 + metabolism * 0.56)


def _life_feedback(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], interactions: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    p = env["paleon"]
    atm = p["atmosphere"]; cycles = p["cycles"]; ocean = p["ocean"]
    live = [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]
    generation = int(world.get("generation", 0))
    if not live:
        return []
    biomass = sum(_species_biomass(s) for s in live)
    scale = biomass / (biomass + 45000.0)
    autotrophy = 0.0; respiration = 0.0; detritivory = 0.0; engineering = 0.0; aquatic_biomass = 0.0
    for s in live:
        b = _species_biomass(s)
        g = s.get("genome", {})
        autotrophy += b * float(g.get("autotrophy", 0.0))
        detritivory += b * float(g.get("detritivory", 0.0))
        respiration += b * (0.35 + float(g.get("carnivory", 0)) * 0.25 + float(g.get("herbivory", 0)) * 0.18)
        engineering += b * float(g.get("engineering", 0.0))
        aquatic_biomass += b * float(g.get("aquatic", 0.0))
    denom = max(1.0, biomass)
    photo = autotrophy / denom
    resp = respiration / denom
    det = detritivory / denom
    eng = engineering / denom
    aquatic = aquatic_biomass / denom
    # Fluxes are deliberately tiny per Git generation: planetary feedback is deep-time behavior.
    co2_flux = (resp * 0.42 - photo * 0.62) * scale * 0.00000055
    o2_flux = (photo * 0.54 - resp * 0.30) * scale * 0.000055
    methane_flux = (max(0.0, float(env.get("moisture", 0.5)) - 0.65) * 0.15 + det * 0.08) * scale * 0.000000012
    atm["co2"] = round(clamp(float(atm.get("co2", 0.00042)) + co2_flux, 0.00008, 0.0035), 9)
    atm["oxygen"] = round(clamp(float(atm.get("oxygen", 0.209)) + o2_flux, 0.08, 0.34), 7)
    atm["methane"] = round(clamp(float(atm.get("methane", 0.0000019)) + methane_flux - float(atm.get("methane", 0.0000019)) * 0.0008, 0.0000002, 0.00008), 10)
    cycles["living_carbon"] = round(clamp(float(cycles.get("living_carbon", 0.48)) * 0.99 + scale * 0.01, 0.02, 1.2), 5)
    decomposition_target = clamp(0.30 + det * 0.38 + float(env.get("temperature", 0.55)) * 0.18, 0.08, 0.9)
    cycles["decomposition"] = round(float(cycles.get("decomposition", 0.42)) * 0.985 + decomposition_target * 0.015, 5)
    nutrient_return = det * 0.003 + float(cycles["decomposition"]) * 0.0015
    cycles["available_nitrogen"] = round(clamp(float(cycles.get("available_nitrogen", 0.56)) + nutrient_return - photo * scale * 0.0013, 0.08, 0.95), 5)
    cycles["available_phosphorus"] = round(clamp(float(cycles.get("available_phosphorus", 0.47)) + nutrient_return * 0.55 - photo * scale * 0.0006, 0.06, 0.92), 5)
    ocean["oxygen"] = round(clamp(float(ocean.get("oxygen", 0.72)) + aquatic * photo * scale * 0.0008 - aquatic * resp * scale * 0.0004, 0.08, 0.95), 5)

    # SOMA ecosystem engineers alter coarse soils and water retention in occupied regions.
    surface = p["surface"]
    w, h = float(env.get("width", 160)), float(env.get("height", 100))
    for s in live:
        g = s.get("genome", {})
        engineering_strength = float(g.get("engineering", 0.0))
        soma = s.get("soma", {})
        body_plan = soma.get("body_plan", {})
        burrow = 0.18 if (float(g.get("burrowing", 0.0)) > 0.56 or "burrow-refuge" in body_plan.get("defenses", [])) else 0.0
        if engineering_strength + burrow < 0.12:
            continue
        for cell in s.get("range", [])[:160]:
            if not isinstance(cell, (list, tuple)) or len(cell) != 2:
                continue
            x = (int(cell[0]) + 0.5) / GRID_COLS * w
            y = (int(cell[1]) + 0.5) / GRID_ROWS * h
            idx = _coarse_index(x, y, env)
            gain = (engineering_strength * 0.0007 + burrow * 0.0004) * min(1.0, float(s.get("population", 0)) / 1500.0)
            surface["soil_fertility"][idx] = round(clamp(float(surface["soil_fertility"][idx]) + gain, 0.02, 1), 5)
            surface["freshwater"][idx] = round(clamp(float(surface["freshwater"][idx]) + gain * 0.55, 0.02, 1), 5)
            surface["succession"][idx] = round(clamp(float(surface["succession"][idx]) + gain * 0.35, 0.02, 1), 5)

    events: list[dict[str, Any]] = []
    tipping = p["tipping"]
    greenhouse_now = _greenhouse_forcing(atm) > 0.095
    icehouse_now = float(p["cryosphere"].get("ice_fraction", 0.1)) > 0.37
    if greenhouse_now and not bool(tipping.get("greenhouse")):
        tipping["greenhouse"] = True
        events.append({"generation": generation, "kind": "climate", "subject": "world", "text": "Atmospheric greenhouse forcing crosses into a persistent warm-state regime."})
    elif not greenhouse_now and bool(tipping.get("greenhouse")) and _greenhouse_forcing(atm) < 0.055:
        tipping["greenhouse"] = False
        events.append({"generation": generation, "kind": "climate", "subject": "world", "text": "Greenhouse forcing falls below the warm-state threshold."})
    if icehouse_now and not bool(tipping.get("icehouse")):
        tipping["icehouse"] = True
        events.append({"generation": generation, "kind": "climate", "subject": "world", "text": "The cryosphere expands into a planetary icehouse interval."})
    elif not icehouse_now and bool(tipping.get("icehouse")) and float(p["cryosphere"].get("ice_fraction", 0.1)) < 0.27:
        tipping["icehouse"] = False
        events.append({"generation": generation, "kind": "climate", "subject": "world", "text": "The planetary icehouse retreats."})
    return events


def _update_global_resources(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], plates: dict[str, Any]) -> None:
    seed = int(world.get("seed", 0))
    # Sample the whole world cheaply; this becomes the global productivity indicator used by legacy systems.
    vals = []
    for gy in range(8):
        for gx in range(12):
            x = (gx + 0.5) / 12 * float(env.get("width", 160))
            y = (gy + 0.5) / 8 * float(env.get("height", 100))
            vals.append(paleon_climate_at(env, plates, x, y, seed)[2])
    env["resources"] = round(clamp(mean(vals), 0.12, 0.98), 5)


def finalize_paleon_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    plates: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Life-to-planet feedback after ecology and SOMA have completed the generation."""
    ensure_paleon_state(world, env, plates, species)
    events = _life_feedback(world, species, env, interactions, rng)
    _update_global_resources(world, species, env, plates)
    p = env["paleon"]
    # Keep a compact long-term planetary record in state without ballooning JSON.
    if int(world.get("generation", 0)) % 10 == 0 or events:
        p.setdefault("history", []).append({
            "generation": int(world.get("generation", 0)),
            "temperature": round(float(env.get("temperature", 0.55)), 4),
            "moisture": round(float(env.get("moisture", 0.53)), 4),
            "productivity": round(float(env.get("resources", 0.69)), 4),
            "co2": p["atmosphere"].get("co2"),
            "oxygen": p["atmosphere"].get("oxygen"),
            "ice": p["cryosphere"].get("ice_fraction"),
            "sea_level": p["cryosphere"].get("sea_level_anomaly"),
            "ocean_oxygen": p["ocean"].get("oxygen"),
            "anoxia": p["ocean"].get("anoxia"),
        })
        p["history"] = p["history"][-180:]
    return events


def validate_paleon_state(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    p = env.get("paleon")
    # Backward-compatible direct unit fixtures may validate an intentionally
    # minimal pre-migration environment. Runtime ensure_schema() always installs
    # PALEON before validating the live world.
    if not isinstance(p, dict):
        return []
    if int(p.get("schema", 0)) != PALEON_SCHEMA_VERSION:
        errors.append("PALEON schema mismatch")
    atm = p.get("atmosphere", {})
    for key, lo, hi in (("co2", 0.00005, 0.004), ("oxygen", 0.05, 0.36), ("methane", 0.0000001, 0.0001), ("aerosols", 0, 1)):
        try:
            val = float(atm.get(key, -1))
            if not lo <= val <= hi:
                errors.append(f"PALEON atmosphere {key} out of bounds")
        except (TypeError, ValueError):
            errors.append(f"PALEON atmosphere {key} invalid")
    ocean = p.get("ocean", {})
    for key in ("heat", "oxygen", "nutrients", "acidity", "circulation", "anoxia"):
        try:
            if not 0 <= float(ocean.get(key, -1)) <= 1:
                errors.append(f"PALEON ocean {key} out of bounds")
        except (TypeError, ValueError):
            errors.append(f"PALEON ocean {key} invalid")
    surface = p.get("surface", {})
    for key in ("soil_fertility", "soil_carbon", "freshwater", "disturbance", "succession", "sediment"):
        arr = surface.get(key)
        if not isinstance(arr, list) or len(arr) != COARSE_COLS * COARSE_ROWS:
            errors.append(f"PALEON surface {key} malformed")
            continue
        if any(not 0 <= float(v) <= 1.2 for v in arr):
            errors.append(f"PALEON surface {key} out of bounds")
    if int(plates.get("paleon_schema", 0)) != PALEON_SCHEMA_VERSION:
        errors.append("PALEON plate schema mismatch")
    for plate in plates.get("plates", []):
        for key in ("crust_age", "thickness", "heat_flux", "stress"):
            try:
                if not 0 <= float(plate.get(key, -1)) <= 1:
                    errors.append(f"PALEON plate {plate.get('id')} {key} out of bounds")
            except (TypeError, ValueError):
                errors.append(f"PALEON plate {plate.get('id')} {key} invalid")
    return errors


def paleon_summary(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any]) -> dict[str, Any]:
    p = env.get("paleon", {})
    return {
        "generation": int(world.get("generation", 0)),
        "temperature": float(env.get("temperature", 0.55)),
        "moisture": float(env.get("moisture", 0.53)),
        "productivity": float(env.get("resources", 0.69)),
        "atmosphere": dict(p.get("atmosphere", {})),
        "ocean": dict(p.get("ocean", {})),
        "cryosphere": dict(p.get("cryosphere", {})),
        "cycles": dict(p.get("cycles", {})),
        "hydrology": dict(p.get("hydrology", {})),
        "plates": len(plates.get("plates", [])),
    }


def _bar(x: float, y: float, w: float, value: float, color: str = "#8eb3a2") -> str:
    value = clamp(value, 0, 1)
    return f'<rect x="{x}" y="{y}" width="{w}" height="8" rx="4" fill="#172526"/><rect x="{x}" y="{y}" width="{w*value:.1f}" height="8" rx="4" fill="{color}"/>'


def render_paleon_assets(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], plates: dict[str, Any], root: Path) -> None:
    """Generate a compact planetary systems plate and static HTML dossier."""
    ensure_paleon_state(world, env, plates, species)
    render_dir = root / "renders"; docs_dir = root / "docs"
    render_dir.mkdir(parents=True, exist_ok=True); docs_dir.mkdir(parents=True, exist_ok=True)
    p = env["paleon"]; atm = p["atmosphere"]; ocean = p["ocean"]; cryo = p["cryosphere"]; cycles = p["cycles"]; hydro = p["hydrology"]
    W, H = 1500, 680
    gen = int(world.get("generation", 0))
    co2_norm = clamp((float(atm.get("co2", 0.00042)) - 0.00008) / (0.0012 - 0.00008), 0, 1)
    oxygen_norm = clamp((float(atm.get("oxygen", 0.209)) - 0.08) / 0.24, 0, 1)
    cols = [
        ("ATMOSPHERE", [("CO2", co2_norm, f"{float(atm.get('co2',0))*1e6:.0f} ppm"), ("OXYGEN", oxygen_norm, f"{float(atm.get('oxygen',0))*100:.2f}%"), ("AEROSOLS", float(atm.get("aerosols", 0)), f"{float(atm.get('aerosols',0)):.3f}")]),
        ("OCEAN", [("HEAT", float(ocean.get("heat", 0)), f"{float(ocean.get('heat',0)):.3f}"), ("OXYGEN", float(ocean.get("oxygen", 0)), f"{float(ocean.get('oxygen',0)):.3f}"), ("ANoxia".upper(), float(ocean.get("anoxia", 0)), f"{float(ocean.get('anoxia',0)):.3f}")]),
        ("CRYOSPHERE", [("ICE", float(cryo.get("ice_fraction", 0)), f"{float(cryo.get('ice_fraction',0))*100:.1f}%"), ("SEA LEVEL", clamp((float(cryo.get("sea_level_anomaly", 0)) + 0.06)/0.12,0,1), f"{float(cryo.get('sea_level_anomaly',0)):+.4f}"), ("SNOWLINE", float(cryo.get("snowline", 0)), f"{float(cryo.get('snowline',0)):.3f}")]),
        ("BIOSPHERE CYCLES", [("NITROGEN", float(cycles.get("available_nitrogen",0)), f"{float(cycles.get('available_nitrogen',0)):.3f}"), ("PHOSPHORUS", float(cycles.get("available_phosphorus",0)), f"{float(cycles.get('available_phosphorus',0)):.3f}"), ("DECOMPOSITION", float(cycles.get("decomposition",0)), f"{float(cycles.get('decomposition',0)):.3f}")]),
        ("HYDROLOGY", [("FRESHWATER", float(hydro.get("global_freshwater",0)), f"{float(hydro.get('global_freshwater',0)):.3f}"), ("RUNOFF", float(hydro.get("runoff",0)), f"{float(hydro.get('runoff',0)):.3f}"), ("STORMINESS", float(hydro.get("storminess",0)), f"{float(hydro.get('storminess',0)):.3f}")]),
    ]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="PHYLUM PALEON planetary systems generation {gen}">', '<rect width="100%" height="100%" fill="#071014"/>', '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#dce8e2}.m{fill:#71867e}.panel{fill:#0b1619;stroke:#253a37}</style>', f'<text x="46" y="54" font-size="24" letter-spacing="5">PHYLUM / PALEON PLANETARY SYSTEM</text>', f'<text x="46" y="82" font-size="12" class="m">DEEP TIME 2.0 · GEN {gen:06d} · LIFE ↔ PLANET FEEDBACK ACTIVE</text>']
    card_w = 270; gap = 18
    for ci, (title, rows) in enumerate(cols):
        x = 46 + ci * (card_w + gap); y = 126
        parts.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="310" rx="9" class="panel"/>')
        parts.append(f'<text x="{x+18}" y="{y+34}" font-size="14" letter-spacing="2">{html.escape(title)}</text>')
        for ri, (label, value, txt) in enumerate(rows):
            yy = y + 78 + ri * 72
            parts.append(f'<text x="{x+18}" y="{yy}" font-size="11" class="m">{html.escape(label)}</text>')
            parts.append(f'<text x="{x+card_w-18}" y="{yy}" text-anchor="end" font-size="12">{html.escape(txt)}</text>')
            parts.append(_bar(x+18, yy+15, card_w-36, float(value)))
    parts.append(f'<rect x="46" y="468" width="{W-92}" height="160" rx="9" class="panel"/>')
    parts.append('<text x="66" y="500" font-size="14" letter-spacing="2">PLANETARY FEEDBACK</text>')
    text_rows = [
        f"GLOBAL TEMP {float(env.get('temperature',0)):.3f}  ·  MOISTURE {float(env.get('moisture',0)):.3f}  ·  PRODUCTIVITY {float(env.get('resources',0)):.3f}",
        f"{len(plates.get('plates',[]))} tectonic plates  ·  greenhouse forcing {float(atm.get('greenhouse_index',0)):+.4f}  ·  ocean circulation {float(ocean.get('circulation',0)):.3f}",
        f"Life changes atmosphere, soil, nutrients and ocean chemistry; those fields feed back into DEEP TIME ecology and SOMA physiology.",
    ]
    for i, row in enumerate(text_rows):
        parts.append(f'<text x="66" y="{535+i*32}" font-size="13" class="{'' if i<2 else 'm'}">{html.escape(row)}</text>')
    parts.append('</svg>')
    (render_dir / "paleon.svg").write_text("".join(parts), encoding="utf-8")

    payload = json.dumps(paleon_summary(world, env, plates), indent=2)
    page = f'''<!doctype html><meta charset="utf-8"><title>PHYLUM / PALEON</title>
<style>body{{background:#071014;color:#dce8e2;font:15px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:0}}main{{max-width:1200px;margin:auto;padding:42px}}h1{{letter-spacing:.18em;font-weight:500}}.muted{{color:#71867e}}img{{width:100%;border:1px solid #253a37}}pre{{background:#0b1619;border:1px solid #253a37;padding:22px;overflow:auto}}</style>
<main><h1>PHYLUM / PALEON</h1><p class="muted">DEEP TIME 2.0 planetary systems dossier · generation {gen:06d}</p><img src="../renders/paleon.svg" alt="PALEON planetary system plate"><h2>Current planetary state</h2><pre>{html.escape(payload)}</pre></main>'''
    (docs_dir / "paleon.html").write_text(page, encoding="utf-8")
