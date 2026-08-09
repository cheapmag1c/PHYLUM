from __future__ import annotations

import hashlib
import colorsys
import html
import json
import math
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
WORLD_PATH = ROOT / "world" / "current.json"
SPECIES_PATH = ROOT / "world" / "species.json"
ENV_PATH = ROOT / "world" / "environment.json"
EVENTS_PATH = ROOT / "fossils" / "events.ndjson"
SPECIES_FOSSIL_DIR = ROOT / "fossils" / "species"
RENDER_PATH = ROOT / "renders" / "current.svg"
PHYLOGENY_PATH = ROOT / "renders" / "phylogeny.svg"
README_PATH = ROOT / "README.md"

README_START = "<!-- PHYLUM:STATE:START -->"
README_END = "<!-- PHYLUM:STATE:END -->"

GRID_COLS = 48
GRID_ROWS = 30

ADJECTIVES = [
    "ashen", "brine", "cinder", "glass", "hollow", "ivory", "mire", "pale",
    "rust", "sable", "silt", "still", "thorn", "velvet", "wither", "wound",
]
NOUNS = [
    "branch", "choir", "crawler", "fan", "filament", "gill", "lace", "mote",
    "petal", "reed", "ribbon", "spine", "veil", "worm", "frond", "bell",
]

EVENT_PRIORITY = {
    "mass_extinction": 100,
    "extinction": 90,
    "speciation": 80,
    "era": 75,
    "climate": 70,
    "colonization": 55,
    "competition": 45,
    "observation": 10,
    "origin": 5,
}

ERA_NAMES = {
    "drought": ("Dry", "Interval"),
    "cooling": ("Pale", "Interval"),
    "bloom": ("Verdant", "Interval"),
    "mass_extinction": ("Ash", "Age"),
    "radiation": ("Radiant", "Age"),
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_state() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    return _load(WORLD_PATH), _load(SPECIES_PATH), _load(ENV_PATH)


def deterministic_rng(seed: int, generation: int, lineage: str) -> random.Random:
    payload = f"{seed}:{generation}:{lineage}".encode()
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _stable_int(value: str) -> int:
    return int(hashlib.sha1(value.encode()).hexdigest()[:12], 16)


def _cell_world_xy(cell: tuple[int, int] | list[int], env: dict[str, Any]) -> tuple[float, float]:
    gx, gy = int(cell[0]), int(cell[1])
    x = (gx + 0.5) * (env["width"] / GRID_COLS)
    y = (gy + 0.5) * (env["height"] / GRID_ROWS)
    return clamp(x, 0, env["width"] - 1), clamp(y, 0, env["height"] - 1)


def _world_to_cell(x: float, y: float, env: dict[str, Any]) -> tuple[int, int]:
    gx = int(clamp(x / max(env["width"], 1) * GRID_COLS, 0, GRID_COLS - 1))
    gy = int(clamp(y / max(env["height"], 1) * GRID_ROWS, 0, GRID_ROWS - 1))
    return gx, gy


def _neighbors(cell: tuple[int, int]) -> Iterable[tuple[int, int]]:
    x, y = cell
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < GRID_COLS and 0 <= ny < GRID_ROWS:
                yield nx, ny


def _normalize_range(sp: dict[str, Any]) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for item in sp.get("range", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            x, y = int(item[0]), int(item[1])
            if 0 <= x < GRID_COLS and 0 <= y < GRID_ROWS:
                result.add((x, y))
    return result


def _store_range(sp: dict[str, Any], cells: set[tuple[int, int]]) -> None:
    sp["range"] = [[x, y] for x, y in sorted(cells, key=lambda c: (c[1], c[0]))]


def env_at(environment: dict[str, Any], x: float, y: float, seed: int) -> tuple[float, float, float]:
    """Procedural local temperature, moisture, and resources in 0..1."""
    w = environment["width"]
    h = environment["height"]
    nx = x / max(w - 1, 1)
    ny = y / max(h - 1, 1)
    phase = (seed % 997) / 997.0 * math.tau

    temp = environment["temperature"]
    temp += 0.18 * math.sin(nx * math.tau + phase)
    temp -= 0.30 * abs(ny - 0.5)

    moisture = environment["moisture"]
    moisture += 0.22 * math.cos((ny * 1.6 + nx * 0.7) * math.tau - phase)

    ridges = 0.5 + 0.5 * math.sin((nx * 3.1 + ny * 2.3) * math.tau + phase)
    resources = environment["resources"] * (0.55 + 0.55 * ridges)
    resources *= 0.75 + 0.35 * clamp(moisture, 0.0, 1.0)

    # Environmental shocks leave persistent, slowly fading local scars.
    for scar in environment.get("scars", []):
        sx = float(scar.get("x", w / 2))
        sy = float(scar.get("y", h / 2))
        radius = max(1.0, float(scar.get("radius", 20)))
        dist = math.dist((x, y), (sx, sy))
        if dist > radius:
            continue
        falloff = 1.0 - dist / radius
        strength = float(scar.get("strength", 0.0)) * falloff
        kind = scar.get("kind")
        if kind == "drought":
            moisture -= strength
            resources -= strength * 0.35
        elif kind == "cooling":
            temp -= strength
        elif kind == "bloom":
            resources += strength
            moisture += strength * 0.12

    return clamp(temp, 0, 1), clamp(moisture, 0, 1), clamp(resources, 0.05, 1.2)


def suitability(sp: dict[str, Any], local: tuple[float, float, float]) -> float:
    t, m, resources = local
    td = abs(t - sp["traits"]["temp_pref"])
    md = abs(m - sp["traits"]["moisture_pref"])
    tolerance = sp["traits"]["tolerance"]
    fit = max(0.0, 1.0 - (td + md) / max(tolerance * 2.0, 0.05))
    return clamp((fit * 0.72) + (min(resources, 1.0) * 0.28), 0, 1)


def _cell_suitability(sp: dict[str, Any], cell: tuple[int, int], env: dict[str, Any], seed: int) -> float:
    return suitability(sp, env_at(env, *_cell_world_xy(cell, env), seed))


def generated_name(rng: random.Random, used: set[str]) -> str:
    for _ in range(100):
        name = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
        if name not in used:
            return name
    return f"lineage {rng.randrange(1000, 9999)}"


def mutate_traits(parent: dict[str, Any], rng: random.Random) -> dict[str, float]:
    p = parent["traits"]
    return {
        "temp_pref": round(clamp(p["temp_pref"] + rng.gauss(0, 0.055), 0.02, 0.98), 4),
        "moisture_pref": round(clamp(p["moisture_pref"] + rng.gauss(0, 0.055), 0.02, 0.98), 4),
        "tolerance": round(clamp(p["tolerance"] + rng.gauss(0, 0.025), 0.10, 0.55), 4),
        "mobility": round(clamp(p["mobility"] + rng.gauss(0, 0.035), 0.03, 0.55), 4),
        "fecundity": round(clamp(p["fecundity"] + rng.gauss(0, 0.035), 0.08, 0.72), 4),
        "body_size": round(clamp(p["body_size"] * math.exp(rng.gauss(0, 0.12)), 0.2, 8.0), 4),
    }


def event(generation: int, kind: str, subject: str, text: str, **extra: Any) -> dict[str, Any]:
    item = {"generation": generation, "kind": kind, "subject": subject, "text": text}
    item.update(extra)
    return item


def _region_name(cell: tuple[int, int]) -> str:
    x, y = cell
    horiz = "western" if x < GRID_COLS / 3 else "eastern" if x >= GRID_COLS * 2 / 3 else "central"
    vert = "northern" if y < GRID_ROWS / 3 else "southern" if y >= GRID_ROWS * 2 / 3 else "midland"
    if horiz == "central" and vert == "midland":
        return "central reach"
    if horiz == "central":
        return f"{vert} reach"
    if vert == "midland":
        return f"{horiz} reach"
    return f"{vert}{horiz} reach"


def _seed_territory(
    sp: dict[str, Any],
    env: dict[str, Any],
    seed: int,
    rng: random.Random,
) -> set[tuple[int, int]]:
    center = _world_to_cell(float(sp.get("x", env["width"] / 2)), float(sp.get("y", env["height"] / 2)), env)
    population = max(1.0, float(sp.get("population", 1.0)))
    desired = int(clamp(round(2 + math.sqrt(population) / 2.1), 3, 18))
    cells = {center}
    while len(cells) < desired:
        frontier = {n for c in cells for n in _neighbors(c) if n not in cells}
        if not frontier:
            break
        ranked = sorted(
            frontier,
            key=lambda c: (_cell_suitability(sp, c, env, seed) + rng.random() * 0.08),
            reverse=True,
        )
        cells.add(ranked[0])
    return cells


def _ensure_schema(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    rng: random.Random,
) -> None:
    world["schema_version"] = max(2, int(world.get("schema_version", 1)))
    world.setdefault("era", {"index": 1, "name": "Origin Era", "started_generation": 0})
    env.setdefault("scars", [])

    for sp in species:
        sp.setdefault("regions_seen", [])
        if sp.get("extinct_generation") is None and not _normalize_range(sp):
            cells = _seed_territory(sp, env, int(world["seed"]), rng)
            _store_range(sp, cells)
            sp["regions_seen"] = sorted({_region_name(c) for c in cells})


def _decay_scars(env: dict[str, Any]) -> None:
    kept = []
    for scar in env.get("scars", []):
        scar = dict(scar)
        scar["strength"] = round(float(scar.get("strength", 0.0)) * 0.992, 5)
        if scar["strength"] >= 0.015:
            kept.append(scar)
    env["scars"] = kept[-18:]


def _add_scar(env: dict[str, Any], kind: str, rng: random.Random, generation: int) -> None:
    env.setdefault("scars", []).append({
        "kind": kind,
        "generation": generation,
        "x": round(rng.uniform(0, env["width"] - 1), 3),
        "y": round(rng.uniform(0, env["height"] - 1), 3),
        "radius": round(rng.uniform(18, 42), 3),
        "strength": round(rng.uniform(0.10, 0.23), 4),
    })
    env["scars"] = env["scars"][-18:]


def _start_era(world: dict[str, Any], generation: int, cause: str, events: list[dict[str, Any]]) -> None:
    current = world.get("era", {"index": 1, "name": "Origin Era", "started_generation": 0})
    if generation - int(current.get("started_generation", 0)) < 12:
        return
    prefix, suffix = ERA_NAMES.get(cause, ("Second", "Age"))
    index = int(current.get("index", 1)) + 1
    name = f"{prefix} {suffix} {index - 1}" if index > 2 else f"{prefix} {suffix}"
    world["era"] = {"index": index, "name": name, "started_generation": generation, "cause": cause}
    events.append(event(generation, "era", "world", f"The {name} begins."))


def _territory_target(sp: dict[str, Any]) -> int:
    population = max(0.0, float(sp.get("population", 0.0)))
    body = max(0.2, float(sp["traits"].get("body_size", 1.0)))
    # Territory scales sublinearly with population and inversely with body size.
    return int(clamp(round(2.0 + math.sqrt(population) / (1.8 * body ** 0.18)), 2, 95))


def _centroid(cells: set[tuple[int, int]], env: dict[str, Any]) -> tuple[float, float]:
    if not cells:
        return env["width"] / 2, env["height"] / 2
    pts = [_cell_world_xy(c, env) for c in cells]
    return (
        sum(p[0] for p in pts) / len(pts),
        sum(p[1] for p in pts) / len(pts),
    )


def _expand_contract_territory(
    sp: dict[str, Any],
    env: dict[str, Any],
    seed: int,
    rng: random.Random,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    cells = _normalize_range(sp)
    if not cells:
        cells = _seed_territory(sp, env, seed, rng)

    old = set(cells)
    target = _territory_target(sp)
    avg_fit = sum(_cell_suitability(sp, c, env, seed) for c in cells) / max(len(cells), 1)
    mobility = float(sp["traits"]["mobility"])

    # Expansion is deliberately gradual so a range has visible history.
    if len(cells) < target or (avg_fit > 0.62 and rng.random() < 0.30):
        attempts = 1 + int(mobility * 8)
        for _ in range(attempts):
            frontier = {n for c in cells for n in _neighbors(c) if n not in cells}
            if not frontier:
                break
            best = max(
                frontier,
                key=lambda c: _cell_suitability(sp, c, env, seed) + rng.random() * (0.04 + mobility * 0.10),
            )
            if _cell_suitability(sp, best, env, seed) >= 0.18 or len(cells) < 2:
                cells.add(best)

    # Poor habitat or a range too large for the population sheds edge cells.
    contract = 0
    if len(cells) > target:
        contract += min(3, len(cells) - target)
    if avg_fit < 0.34 and len(cells) > 2:
        contract += 1
    for _ in range(contract):
        if len(cells) <= 1:
            break
        # Prefer removing poor, peripheral cells.
        cx = sum(c[0] for c in cells) / len(cells)
        cy = sum(c[1] for c in cells) / len(cells)
        worst = min(
            cells,
            key=lambda c: _cell_suitability(sp, c, env, seed) - 0.025 * math.dist((c[0], c[1]), (cx, cy)),
        )
        cells.remove(worst)

    return cells, cells - old


def _resolve_competition(
    living: list[dict[str, Any]],
    env: dict[str, Any],
    seed: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    claims: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for sp in living:
        for cell in _normalize_range(sp):
            claims.setdefault(cell, []).append(sp)

    lost: dict[str, int] = {sp["id"]: 0 for sp in living}
    for cell, contenders in claims.items():
        if len(contenders) <= 1:
            continue

        def score(sp: dict[str, Any]) -> float:
            fit = _cell_suitability(sp, cell, env, seed)
            pop = math.log1p(float(sp["population"])) / 10.0
            body = min(0.10, float(sp["traits"]["body_size"]) * 0.015)
            return fit + pop + body + rng.random() * 0.035

        winner = max(contenders, key=score)
        for sp in contenders:
            if sp is winner:
                continue
            cells = _normalize_range(sp)
            if cell in cells and len(cells) > 1:
                cells.remove(cell)
                lost[sp["id"]] += 1
                _store_range(sp, cells)

    # Only record meaningful clashes, not every one-cell brush.
    events: list[dict[str, Any]] = []
    generation = 0
    for sp in living:
        if lost[sp["id"]] >= 3:
            generation = max(generation, int(sp.get("_generation", 0)))
            events.append(event(
                generation,
                "competition",
                sp["id"],
                f"{sp['name']} loses ground to a competing lineage.",
            ))
    return events


def _update_population(
    sp: dict[str, Any],
    env: dict[str, Any],
    seed: int,
    rng: random.Random,
) -> None:
    cells = _normalize_range(sp)
    if not cells:
        sp["population"] = 0.0
        sp["last_fitness"] = 0.0
        return

    locals_ = [env_at(env, *_cell_world_xy(c, env), seed) for c in cells]
    fits = [suitability(sp, local) for local in locals_]
    fit = sum(fits) / len(fits)

    body_cost = 0.014 * sp["traits"]["body_size"]
    growth = (fit - 0.46 - body_cost) * sp["traits"]["fecundity"]
    noise = rng.gauss(0, 0.030)
    next_pop = max(0.0, sp["population"] * (1.0 + growth + noise))

    # Each occupied cell contributes carrying capacity; this makes territorial
    # expansion biologically meaningful rather than cosmetic.
    resource_sum = sum(local[2] for local in locals_)
    carrying = 245.0 * resource_sum / max(0.38, sp["traits"]["body_size"] ** 0.45)
    if next_pop > carrying:
        next_pop = carrying + (next_pop - carrying) * 0.12

    sp["population"] = round(next_pop, 2)
    sp["last_fitness"] = round(fit, 4)


def _update_position_from_range(sp: dict[str, Any], env: dict[str, Any]) -> None:
    cells = _normalize_range(sp)
    if not cells:
        return
    x, y = _centroid(cells, env)
    sp["x"] = round(x, 3)
    sp["y"] = round(y, 3)


def _archive_species(sp: dict[str, Any]) -> None:
    SPECIES_FOSSIL_DIR.mkdir(parents=True, exist_ok=True)
    _save(SPECIES_FOSSIL_DIR / f"{sp['id']}.json", sp)


def _maybe_colonization_events(
    sp: dict[str, Any],
    new_cells: set[tuple[int, int]],
    generation: int,
) -> list[dict[str, Any]]:
    seen = set(sp.get("regions_seen", []))
    events = []
    for cell in sorted(new_cells):
        region = _region_name(cell)
        if region in seen:
            continue
        seen.add(region)
        # Don't make the fossil log noisy during the initial territory migration.
        if generation > int(sp.get("born_generation", 0)) + 1:
            events.append(event(
                generation,
                "colonization",
                sp["id"],
                f"{sp['name']} reaches the {region}.",
            ))
    sp["regions_seen"] = sorted(seen)
    return events[:1]


def _split_territory(
    parent: dict[str, Any],
    env: dict[str, Any],
    rng: random.Random,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    cells = _normalize_range(parent)
    if len(cells) < 4:
        return cells, set()

    cx = sum(c[0] for c in cells) / len(cells)
    cy = sum(c[1] for c in cells) / len(cells)
    ordered = sorted(cells, key=lambda c: math.dist((c[0], c[1]), (cx, cy)), reverse=True)
    take = int(clamp(round(len(cells) * rng.uniform(0.22, 0.38)), 2, max(2, len(cells) - 2)))
    child = set(ordered[:take])

    # Grow the child selection around its farthest seed so it is geographically coherent.
    seed_cell = ordered[0]
    child = {seed_cell}
    while len(child) < take:
        frontier = {n for c in child for n in _neighbors(c) if n in cells and n not in child}
        if not frontier:
            break
        child.add(max(frontier, key=lambda c: math.dist((c[0], c[1]), (cx, cy))))

    parent_cells = cells - child
    if not parent_cells:
        return cells, set()
    return parent_cells, child


def evolve_one(lineage: str | None = None) -> dict[str, Any]:
    world, species, env = load_state()
    next_gen = int(world["generation"]) + 1
    lineage = lineage or os.getenv("GITHUB_REPOSITORY") or world.get("active_lineage") or "origin"
    rng = deterministic_rng(int(world["seed"]), next_gen, lineage)
    events: list[dict[str, Any]] = []

    _ensure_schema(world, species, env, rng)
    _decay_scars(env)

    # Slow climate drift.
    env["temperature"] = round(clamp(env["temperature"] + rng.gauss(0, 0.006), 0.10, 0.90), 4)
    env["moisture"] = round(clamp(env["moisture"] + rng.gauss(0, 0.008), 0.08, 0.92), 4)
    env["resources"] = round(clamp(env["resources"] + rng.gauss(0, 0.010), 0.35, 1.00), 4)

    # Rare global events now leave geographical scars.
    shock_roll = rng.random()
    shock_kind: str | None = None
    if shock_roll < 0.012:
        shock_kind = "drought"
        env["moisture"] = round(clamp(env["moisture"] - rng.uniform(0.06, 0.14), 0.05, 0.95), 4)
        _add_scar(env, "drought", rng, next_gen)
        events.append(event(next_gen, "climate", "drought", "A prolonged dry phase scars the habitat."))
    elif shock_roll < 0.020:
        shock_kind = "cooling"
        env["temperature"] = round(clamp(env["temperature"] - rng.uniform(0.06, 0.12), 0.05, 0.95), 4)
        _add_scar(env, "cooling", rng, next_gen)
        events.append(event(next_gen, "climate", "cooling", "A rapid cooling phase alters the habitat."))
    elif shock_roll < 0.030:
        shock_kind = "bloom"
        env["resources"] = round(clamp(env["resources"] + rng.uniform(0.07, 0.16), 0.35, 1.0), 4)
        _add_scar(env, "bloom", rng, next_gen)
        events.append(event(next_gen, "climate", "bloom", "A resource bloom spreads across the world."))

    if shock_kind:
        _start_era(world, next_gen, shock_kind, events)

    alive_before = [s for s in species if s.get("extinct_generation") is None]
    used_names = {s["name"] for s in species}
    newborns: list[dict[str, Any]] = []

    # Phase 1: geographic range movement.
    for sp in alive_before:
        sp["_generation"] = next_gen
        cells, gained = _expand_contract_territory(sp, env, int(world["seed"]), rng)
        _store_range(sp, cells)
        events.extend(_maybe_colonization_events(sp, gained, next_gen))

    events.extend(_resolve_competition(alive_before, env, int(world["seed"]), rng))

    # Phase 2: population dynamics, extinction, and speciation.
    extinct_this_gen = 0
    for sp in alive_before:
        _update_population(sp, env, int(world["seed"]), rng)
        _update_position_from_range(sp, env)

        if sp["population"] < 2.0 or not _normalize_range(sp):
            sp["population"] = 0.0
            sp["extinct_generation"] = next_gen
            sp.pop("_generation", None)
            _archive_species(sp)
            extinct_this_gen += 1
            events.append(event(next_gen, "extinction", sp["id"], f"{sp['name']} becomes extinct."))
            continue

        age = next_gen - int(sp["born_generation"])
        territory_cells = len(_normalize_range(sp))
        speciation_p = 0.0025
        speciation_p += min(0.010, sp["population"] / 350000.0)
        speciation_p += min(0.004, age / 20000.0)
        speciation_p += min(0.005, territory_cells / 9000.0)

        if age >= 8 and sp["population"] >= 80 and territory_cells >= 4 and rng.random() < speciation_p:
            parent_range, child_range = _split_territory(sp, env, rng)
            if child_range:
                child_id = f"sp-{world['next_species_id']:05d}"
                world["next_species_id"] += 1
                child_pop = max(12.0, sp["population"] * rng.uniform(0.08, 0.20))
                sp["population"] = round(max(2.0, sp["population"] - child_pop), 2)
                _store_range(sp, parent_range)

                child_name = generated_name(rng, used_names)
                used_names.add(child_name)
                child = {
                    "id": child_id,
                    "name": child_name,
                    "parent_id": sp["id"],
                    "born_generation": next_gen,
                    "extinct_generation": None,
                    "population": round(child_pop, 2),
                    "traits": mutate_traits(sp, rng),
                    "last_fitness": sp["last_fitness"],
                    "regions_seen": sorted({_region_name(c) for c in child_range}),
                }
                _store_range(child, child_range)
                _update_position_from_range(child, env)
                newborns.append(child)
                events.append(event(
                    next_gen,
                    "speciation",
                    child_id,
                    f"{child_name} diverges from {sp['name']} along a separated range.",
                    parent_id=sp["id"],
                ))

        sp.pop("_generation", None)

    species.extend(newborns)

    living = [s for s in species if s.get("extinct_generation") is None]
    total_pop = round(sum(s["population"] for s in living), 2)

    # A real collapse becomes a named geological boundary.
    if alive_before and extinct_this_gen >= max(2, math.ceil(len(alive_before) * 0.40)):
        events.append(event(
            next_gen,
            "mass_extinction",
            "world",
            f"A mass extinction removes {extinct_this_gen} lineages.",
        ))
        _start_era(world, next_gen, "mass_extinction", events)

    world["generation"] = next_gen
    world["active_lineage"] = lineage
    world["last_evolved_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    world["living_species"] = len(living)
    world["extinct_species"] = len(species) - len(living)
    world["total_population"] = total_pop
    world["occupied_cells"] = len({tuple(c) for s in living for c in s.get("range", [])})

    if len(living) == 0:
        events.append(event(next_gen, "world", "sterile", "No living lineages remain."))

    # Record a periodic fossil even when no major event occurred.
    if not events and next_gen % 25 == 0:
        dominant = max(living, key=lambda s: s["population"], default=None)
        detail = "The biosphere remains stable."
        if dominant:
            detail = f"{dominant['name']} is the most abundant lineage."
        events.append(event(next_gen, "observation", "survey", detail))

    _save(WORLD_PATH, world)
    _save(SPECIES_PATH, species)
    _save(ENV_PATH, env)
    append_events(events)
    render_svg(world, species, env)
    render_phylogeny(world, species)
    update_readme(world, species, env, events)
    return {"world": world, "species": species, "environment": env, "events": events}


def append_events(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, sort_keys=True) + "\n")


def _biome_color(temp: float, moisture: float, resources: float) -> str:
    if temp < 0.28:
        return "#c7c8bd" if moisture > 0.5 else "#a9aaa3"
    if moisture < 0.28:
        return "#9a8467"
    if moisture > 0.68 and resources > 0.72:
        return "#526654"
    if resources > 0.78:
        return "#66745b"
    if temp > 0.70:
        return "#806c52"
    return "#6c705e"


def _species_hue(sp_id: str) -> int:
    return _stable_int(sp_id) % 360


def _species_color(sp_id: str, lightness: float = 0.68, saturation: float = 0.52) -> str:
    hue = _species_hue(sp_id) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f"#{round(r*255):02x}{round(g*255):02x}{round(b*255):02x}"


def render_svg(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any]) -> None:
    width_px, height_px = 960, 600
    cw, ch = width_px / GRID_COLS, height_px / GRID_ROWS
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_px} {height_px}" role="img" aria-label="PHYLUM generation {world["generation"]}">',
        '<rect width="100%" height="100%" fill="#11110f"/>',
    ]

    for gy in range(GRID_ROWS):
        for gx in range(GRID_COLS):
            x, y = _cell_world_xy((gx, gy), env)
            t, m, r = env_at(env, x, y, world["seed"])
            c = _biome_color(t, m, r)
            parts.append(
                f'<rect x="{gx*cw:.2f}" y="{gy*ch:.2f}" width="{cw+0.4:.2f}" '
                f'height="{ch+0.4:.2f}" fill="{c}"/>'
            )

    # Shock epicenters remain visible as restrained cartographic scars.
    for scar in env.get("scars", []):
        px = scar["x"] / (env["width"] - 1) * width_px
        py = scar["y"] / (env["height"] - 1) * height_px
        rr = scar["radius"] / env["width"] * width_px
        strength = clamp(float(scar.get("strength", 0)), 0.02, 0.30)
        parts.append(
            f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{rr:.2f}" fill="none" '
            f'stroke="#161512" stroke-opacity="{0.18 + strength:.3f}" stroke-width="2" '
            f'stroke-dasharray="4 5"><title>{html.escape(str(scar.get("kind", "environmental scar")))}</title></circle>'
        )

    # Subtle contour-like lines.
    for i in range(1, 10):
        y = i * height_px / 10
        parts.append(
            f'<path d="M 0 {y:.1f} C 220 {y-24:.1f}, 420 {y+26:.1f}, 620 {y-10:.1f} '
            f'S 840 {y+20:.1f}, 960 {y:.1f}" fill="none" stroke="#11110f" '
            f'stroke-opacity="0.12" stroke-width="1"/>'
        )

    living = [s for s in species if s.get("extinct_generation") is None and s["population"] > 0]

    # Render extinct ranges first as quiet fossil outlines.
    recent_extinct = sorted(
        (s for s in species if s.get("extinct_generation") is not None and s.get("range")),
        key=lambda s: int(s["extinct_generation"]),
        reverse=True,
    )[:18]
    for sp in recent_extinct:
        for gx, gy in _normalize_range(sp):
            parts.append(
                f'<rect x="{gx*cw+1.2:.2f}" y="{gy*ch+1.2:.2f}" width="{cw-2.4:.2f}" '
                f'height="{ch-2.4:.2f}" fill="none" stroke="#171612" stroke-opacity="0.28" '
                f'stroke-width="1" stroke-dasharray="2 3"/>'
            )

    # Living lineages are literal geographical ranges now.
    for sp in sorted(living, key=lambda s: s["population"]):
        fill_color = _species_color(sp["id"], 0.68, 0.52)
        stroke_color = _species_color(sp["id"], 0.30, 0.58)
        cells = _normalize_range(sp)
        for gx, gy in cells:
            parts.append(
                f'<rect x="{gx*cw+0.7:.2f}" y="{gy*ch+0.7:.2f}" width="{cw-1.4:.2f}" '
                f'height="{ch-1.4:.2f}" rx="2" fill="{fill_color}" '
                f'fill-opacity="0.58" stroke="{stroke_color}" stroke-opacity="0.65" '
                f'stroke-width="0.8"><title>{html.escape(sp["name"])} — {int(sp["population"])} organisms</title></rect>'
            )

    # Labels sit at range centroids.
    max_pop = max((s["population"] for s in living), default=1.0)
    for sp in living:
        cells = _normalize_range(sp)
        if not cells:
            continue
        x, y = _centroid(cells, env)
        px = x / (env["width"] - 1) * width_px
        py = y / (env["height"] - 1) * height_px
        if sp["population"] == max_pop or len(living) <= 10:
            label = html.escape(sp["name"])
            parts.append(
                f'<circle cx="{px:.2f}" cy="{py:.2f}" r="3.2" fill="#f1efe7" stroke="#11110f" stroke-width="1"/>'
            )
            parts.append(
                f'<text x="{px+7:.2f}" y="{py+4:.2f}" font-family="ui-monospace, monospace" '
                f'font-size="12" fill="#f1efe7" stroke="#11110f" stroke-width="1.3" '
                f'paint-order="stroke">{label}</text>'
            )

    era = world.get("era", {}).get("name", "Origin Era")
    parts.append('<rect x="16" y="16" width="310" height="91" rx="3" fill="#11110f" fill-opacity="0.84"/>')
    parts.append(
        f'<text x="30" y="43" font-family="ui-monospace, monospace" font-size="20" fill="#f1efe7">'
        f'PHYLUM / GEN {world["generation"]:06d}</text>'
    )
    parts.append(
        f'<text x="30" y="66" font-family="ui-monospace, monospace" font-size="12" fill="#c9c5b8">'
        f'{len(living)} living lineages · {int(world["total_population"])} organisms · '
        f'{world.get("occupied_cells", 0)} occupied cells</text>'
    )
    parts.append(
        f'<text x="30" y="88" font-family="ui-monospace, monospace" font-size="12" fill="#c9c5b8">'
        f'ERA / {html.escape(str(era).upper())}</text>'
    )
    parts.append('</svg>')

    RENDER_PATH.parent.mkdir(parents=True, exist_ok=True)
    RENDER_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")


def render_phylogeny(world: dict[str, Any], species: list[dict[str, Any]]) -> None:
    # Keep the artifact readable even after the biosphere becomes huge.
    roots = [s for s in species if not s.get("parent_id")]
    recent = sorted(species, key=lambda s: int(s.get("born_generation", 0)), reverse=True)
    selected_ids = {s["id"] for s in roots}
    for sp in recent:
        if len(selected_ids) >= 120:
            break
        selected_ids.add(sp["id"])
        parent = sp.get("parent_id")
        while parent and len(selected_ids) < 120:
            selected_ids.add(parent)
            parent_sp = next((x for x in species if x["id"] == parent), None)
            parent = parent_sp.get("parent_id") if parent_sp else None

    selected = [s for s in species if s["id"] in selected_ids]
    selected.sort(key=lambda s: (int(s.get("born_generation", 0)), s["id"]))
    index = {s["id"]: i for i, s in enumerate(selected)}

    width = 960
    height = max(220, 95 + len(selected) * 22)
    left, right = 165, width - 55
    current_gen = max(1, int(world["generation"]))

    def x_for(gen: int) -> float:
        return left + (right - left) * (gen / current_gen)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="PHYLUM phylogeny">',
        '<rect width="100%" height="100%" fill="#151511"/>',
        '<text x="28" y="37" font-family="ui-monospace, monospace" font-size="20" fill="#f1efe7">PHYLUM / PHYLOGENY</text>',
        f'<text x="28" y="60" font-family="ui-monospace, monospace" font-size="11" fill="#aaa698">'
        f'{len(species)} recorded lineages · generation {world["generation"]:06d}</text>',
    ]

    positions: dict[str, tuple[float, float]] = {}
    for i, sp in enumerate(selected):
        y = 92 + i * 22
        born = int(sp.get("born_generation", 0))
        x = x_for(born)
        positions[sp["id"]] = (x, y)

    for sp in selected:
        parent = sp.get("parent_id")
        if parent in positions:
            px, py = positions[parent]
            x, y = positions[sp["id"]]
            parts.append(
                f'<path d="M {px:.1f} {py:.1f} C {(px+x)/2:.1f} {py:.1f}, {(px+x)/2:.1f} {y:.1f}, {x:.1f} {y:.1f}" '
                f'fill="none" stroke="#6e6b61" stroke-width="1.2" stroke-opacity="0.75"/>'
            )

    for sp in selected:
        x, y = positions[sp["id"]]
        fill_color = _species_color(sp["id"], 0.68, 0.52)
        extinct = sp.get("extinct_generation") is not None
        fill_opacity = 0.34 if extinct else 0.90
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{fill_color}" '
            f'fill-opacity="{fill_opacity}" stroke="#0c0c0a" stroke-width="1"/>'
        )
        state = f"† {sp['extinct_generation']}" if extinct else f"{int(sp['population'])} alive"
        label = html.escape(sp["name"])
        parts.append(
            f'<text x="28" y="{y+4:.1f}" font-family="ui-monospace, monospace" font-size="11" '
            f'fill="{"#88857a" if extinct else "#e8e5dc"}">{label}</text>'
        )
        parts.append(
            f'<text x="{x+9:.1f}" y="{y+4:.1f}" font-family="ui-monospace, monospace" font-size="9" '
            f'fill="#8f8b80">{html.escape(state)}</text>'
        )

    if len(species) > len(selected):
        parts.append(
            f'<text x="28" y="{height-18}" font-family="ui-monospace, monospace" font-size="10" fill="#77746a">'
            f'{len(species)-len(selected)} older/secondary nodes omitted from this render</text>'
        )
    parts.append("</svg>")
    PHYLOGENY_PATH.parent.mkdir(parents=True, exist_ok=True)
    PHYLOGENY_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")


def update_readme(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    if not README_PATH.exists():
        return
    text = README_PATH.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return

    living = [s for s in species if s.get("extinct_generation") is None]
    dominant = max(living, key=lambda s: s["population"], default=None)
    last_event = events[-1]["text"] if events else latest_event_text()
    era = world.get("era", {}).get("name", "Origin Era")
    block = [
        README_START,
        f"**Generation:** `{world['generation']:,}`  ",
        f"**Era:** `{era}`  ",
        f"**Living lineages:** `{len(living)}`  ",
        f"**Extinct lineages:** `{world['extinct_species']}`  ",
        f"**Population:** `{int(world['total_population']):,}`  ",
        f"**Occupied cells:** `{world.get('occupied_cells', 0):,}` / `{GRID_COLS * GRID_ROWS:,}`  ",
        f"**Dominant lineage:** `{dominant['name'] if dominant else 'none'}`  ",
        f"**Latest fossil:** {last_event or 'No major event recorded yet.'}",
        README_END,
    ]
    before, rest = text.split(README_START, 1)
    _, after = rest.split(README_END, 1)
    text = before + "\n".join(block) + after

    # Add the living family tree to older repositories the first time v0.2 runs.
    if "![PHYLUM phylogeny]" not in text:
        tree_block = "\n## Living phylogeny\n\n![PHYLUM phylogeny](renders/phylogeny.svg)\n\n"
        if "## The idea" in text:
            text = text.replace("## The idea", tree_block + "## The idea", 1)
        else:
            text += tree_block

    # GitHub caches relative SVGs aggressively. Changing the query each generation
    # gives the observation window a fresh URL without generating extra files.
    text = re.sub(
        r"!\[Current PHYLUM world\]\(renders/current\.svg(?:\?gen=\d+)?\)",
        f"![Current PHYLUM world](renders/current.svg?gen={world['generation']:06d})",
        text,
    )
    text = re.sub(
        r"!\[PHYLUM phylogeny\]\(renders/phylogeny\.svg(?:\?gen=\d+)?\)",
        f"![PHYLUM phylogeny](renders/phylogeny.svg?gen={world['generation']:06d})",
        text,
    )
    README_PATH.write_text(text, encoding="utf-8")


def latest_event() -> dict[str, Any] | None:
    if not EVENTS_PATH.exists():
        return None
    lines = [line for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        value = json.loads(lines[-1])
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def latest_event_text() -> str | None:
    item = latest_event()
    return item.get("text") if item else None


def _current_generation_events(generation: int) -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    result = []
    for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict) and int(item.get("generation", -1)) == generation:
            result.append(item)
    return result


def commit_message() -> str:
    world, _, _ = load_state()
    generation = int(world["generation"])
    current = _current_generation_events(generation)
    if current:
        fossil = max(current, key=lambda e: EVENT_PRIORITY.get(str(e.get("kind")), 20))
        summary = str(fossil.get("text", "world advances")).rstrip(".")
        return f"gen {generation:06d} — {summary[:68]}"
    return f"gen {generation:06d} — biosphere advances"
