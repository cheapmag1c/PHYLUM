from __future__ import annotations

import copy
import html
import json
import math
import random
from pathlib import Path
from typing import Any

from .constants import GRID_COLS, GRID_ROWS
from .utils import clamp, stable_int

TECHNE_SCHEMA_VERSION = 1
MAX_PRACTICES = 24
MAX_SITES = 240
MAX_ARCHIVE = 800
MAX_CULTURAL_LINEAGES = 600


# TECHNE deliberately models culture at population scale. A "site" is a persistent
# archaeological/cultural location, not one object per organism.


def _genome(sp: dict[str, Any]) -> dict[str, float]:
    return {str(k): float(v) for k, v in sp.get("genome", {}).items() if isinstance(v, (int, float))}


def _cells(sp: dict[str, Any]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for item in sp.get("range", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                x, y = int(item[0]), int(item[1])
            except (TypeError, ValueError):
                continue
            if 0 <= x < GRID_COLS and 0 <= y < GRID_ROWS:
                out.add((x, y))
    return out


def _centroid(sp: dict[str, Any]) -> list[float] | None:
    cells = _cells(sp)
    if not cells:
        return None
    return [round(sum(x for x, _ in cells) / len(cells), 3), round(sum(y for _, y in cells) / len(cells), 3)]


def _nerve(sp: dict[str, Any]) -> dict[str, Any]:
    return sp.get("nerve", {}) if isinstance(sp.get("nerve"), dict) else {}


def _soma(sp: dict[str, Any]) -> dict[str, Any]:
    return sp.get("soma", {}) if isinstance(sp.get("soma"), dict) else {}


def _base_capacities(sp: dict[str, Any]) -> dict[str, float]:
    nerve = _nerve(sp)
    arch = nerve.get("architecture", {})
    social = nerve.get("social", {})
    manip = nerve.get("manipulation", {})
    temp = nerve.get("temperament", {})
    g = _genome(sp)
    neural = float(arch.get("neural_complexity", 0.08))
    learning = float(arch.get("learning_rate", 0.06))
    memory = float(arch.get("memory_capacity", 0.06))
    planning = float(arch.get("planning_horizon", 0.0))
    signal = float(social.get("signal_complexity", 0.08))
    teaching = float(social.get("teaching", 0.0))
    cooperation = float(social.get("cooperation", 0.1))
    transmission = float(nerve.get("culture", {}).get("transmission", 0.0))
    manipulation = float(manip.get("score", 0.0))
    engineering = float(g.get("engineering", 0.0))
    curiosity = float(temp.get("curiosity", 0.1))
    cultural_storage = clamp(memory * 0.30 + learning * 0.26 + signal * 0.18 + cooperation * 0.12 + transmission * 0.14, 0, 1)
    innovation = clamp(neural * 0.23 + learning * 0.24 + planning * 0.16 + curiosity * 0.12 + manipulation * 0.12 + engineering * 0.13, 0, 1)
    material = clamp(manipulation * 0.48 + engineering * 0.28 + planning * 0.16 + learning * 0.08, 0, 1)
    construction = clamp(material * 0.55 + cooperation * 0.18 + planning * 0.17 + engineering * 0.10, 0, 1)
    language = clamp(signal * 0.43 + teaching * 0.16 + neural * 0.16 + memory * 0.13 + cooperation * 0.12, 0, 1)
    transmission2 = clamp(transmission * 0.58 + teaching * 0.15 + learning * 0.13 + cooperation * 0.14, 0, 1)
    return {
        "cultural_storage": round(cultural_storage, 5),
        "innovation": round(innovation, 5),
        "material_skill": round(material, 5),
        "construction": round(construction, 5),
        "language": round(language, 5),
        "transmission": round(transmission2, 5),
    }


def _dialect_seed(sp: dict[str, Any], seed: int) -> dict[str, Any]:
    nerve = _nerve(sp)
    comm = nerve.get("social", {}).get("communication", ["chemical"])
    if not isinstance(comm, list) or not comm:
        comm = ["chemical"]
    family = "+".join(str(x) for x in comm[:2])
    variant = stable_int(f"techne:dialect:{seed}:{sp.get('id')}") % 100000
    return {"family": family, "variant": f"d-{variant:05d}", "divergence": 0.0}


def _base_techne(sp: dict[str, Any], seed: int) -> dict[str, Any]:
    return {
        "schema": TECHNE_SCHEMA_VERSION,
        "capacities": _base_capacities(sp),
        "practices": [],
        "dialect": _dialect_seed(sp, seed),
        "modifiers": {},
        "selection_pressures": {"culture": 0.0, "construction": 0.0, "communication": 0.0},
        "statistics": {"innovations": 0, "lost_practices": 0, "received_practices": 0, "sites_created": 0},
        "experience_generations": 0,
    }


def ensure_world_techne(world: dict[str, Any]) -> dict[str, Any]:
    t = world.setdefault("techne", {})
    if not isinstance(t, dict):
        world["techne"] = t = {}
    t["schema"] = TECHNE_SCHEMA_VERSION
    t.setdefault("sites", [])
    t.setdefault("archive", [])
    t.setdefault("cultural_lineages", [])
    t.setdefault("next_site_id", 1)
    t.setdefault("next_culture_id", 1)
    t.setdefault("statistics", {})
    t["sites"] = [x for x in t.get("sites", []) if isinstance(x, dict)][-MAX_SITES:]
    t["archive"] = [x for x in t.get("archive", []) if isinstance(x, dict)][-MAX_ARCHIVE:]
    t["cultural_lineages"] = [x for x in t.get("cultural_lineages", []) if isinstance(x, dict)][-MAX_CULTURAL_LINEAGES:]
    return t


def _inherit_techne(parent: dict[str, Any], child: dict[str, Any], seed: int) -> dict[str, Any]:
    out = _base_techne(child, seed)
    p = parent.get("techne", {})
    transmission = float(p.get("capacities", {}).get("transmission", 0.0))
    if transmission < 0.28:
        return out
    inherited: list[dict[str, Any]] = []
    for row in sorted(p.get("practices", []), key=lambda x: float(x.get("strength", 0)), reverse=True)[:5]:
        strength = float(row.get("strength", 0)) * (0.38 + transmission * 0.35)
        if strength < 0.09:
            continue
        cp = copy.deepcopy(row)
        cp["strength"] = round(clamp(strength, 0, 1), 4)
        cp["founder_inherited"] = True
        cp["last_generation"] = int(child.get("born_generation", 0))
        inherited.append(cp)
    out["practices"] = inherited
    return out


def ensure_techne_schema(
    sp: dict[str, Any],
    seed: int,
    generation: int,
    species_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parent = (species_by_id or {}).get(str(sp.get("parent_id"))) if sp.get("parent_id") else None
    if not isinstance(sp.get("techne"), dict) or not sp.get("techne"):
        sp["techne"] = _inherit_techne(parent, sp, seed) if parent and parent.get("techne") else _base_techne(sp, seed)
        # NERVE traditions are pre-technological cultural evidence. SOMA/TECHNE does
        # not erase them; it imports strong ones as weak founding practices.
        for tr in _nerve(sp).get("culture", {}).get("traditions", [])[-4:]:
            strength = float(tr.get("strength", 0)) * 0.55
            if strength >= 0.10:
                sp["techne"]["practices"].append({
                    "id": f"p-{stable_int('{}:{}'.format(sp.get('id'), tr.get('id', tr.get('name')))) % 1000000:06d}",
                    "name": str(tr.get("name", "inherited tradition")),
                    "category": "tradition",
                    "origin_generation": int(tr.get("origin_generation", generation)),
                    "last_generation": generation,
                    "strength": round(strength, 4),
                    "lineage_id": None,
                    "nerve_origin": True,
                })
    else:
        techne = sp["techne"]
        techne["schema"] = TECHNE_SCHEMA_VERSION
        base = _base_techne(sp, seed)
        techne.setdefault("capacities", {})
        for k, v in base["capacities"].items():
            techne["capacities"].setdefault(k, v)
        techne.setdefault("practices", [])
        techne.setdefault("dialect", base["dialect"])
        techne.setdefault("modifiers", {})
        techne.setdefault("selection_pressures", base["selection_pressures"])
        techne.setdefault("statistics", base["statistics"])
        techne.setdefault("experience_generations", 0)
    sp["techne"]["practices"] = [x for x in sp["techne"].get("practices", []) if isinstance(x, dict)][-MAX_PRACTICES:]
    return sp["techne"]


def _practice_names(sp: dict[str, Any]) -> set[str]:
    return {str(p.get("name")) for p in sp.get("techne", {}).get("practices", [])}


def _practice_strength(sp: dict[str, Any], name: str) -> float:
    for p in sp.get("techne", {}).get("practices", []):
        if p.get("name") == name:
            return float(p.get("strength", 0))
    return 0.0


def _modifiers(sp: dict[str, Any]) -> dict[str, float]:
    names = _practice_names(sp)
    n = len(names)
    energy = 1.0
    capacity = 1.0
    mortality = 1.0
    migration = 1.0
    if "food caching" in names: energy += 0.025
    if "persistent nesting" in names: mortality -= 0.018
    if "constructed shelter" in names: mortality -= 0.025; capacity += 0.012
    if "resource tending" in names: energy += 0.035; capacity += 0.022
    if "water control" in names: capacity += 0.035
    if "route marking" in names: migration += 0.035
    if "object selection" in names: energy += 0.018
    if "object modification" in names: energy += 0.028
    if "compound tools" in names: energy += 0.035
    # Cultural storage is useful but it is not free. The overhead prevents a simple
    # monotonic "more practices = always better" progression.
    overhead = min(0.045, n * 0.0022)
    energy -= overhead
    return {
        "energy_efficiency": round(clamp(energy, 0.94, 1.14), 5),
        "capacity": round(clamp(capacity, 0.97, 1.10), 5),
        "mortality": round(clamp(mortality + overhead * 0.10, 0.92, 1.04), 5),
        "migration": round(clamp(migration, 0.98, 1.08), 5),
    }


def prepare_techne_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    ensure_world_techne(world)
    generation = int(world.get("generation", 0))
    seed = int(world.get("seed", 0))
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    for sp in species:
        if sp.get("extinct_generation") is not None or float(sp.get("population", 0)) <= 0:
            continue
        techne = ensure_techne_schema(sp, seed, generation, by_id)
        base = _base_capacities(sp)
        caps = techne.setdefault("capacities", {})
        for key, val in base.items():
            caps[key] = round(clamp(float(caps.get(key, val)) * 0.86 + float(val) * 0.14, 0, 1), 5)
        techne["modifiers"] = _modifiers(sp)
    return []


def _new_cultural_lineage(world: dict[str, Any], sp: dict[str, Any], practice: str, generation: int, parent_id: str | None = None) -> str:
    t = ensure_world_techne(world)
    cid = f"cu-{int(t.get('next_culture_id',1)):06d}"
    t["next_culture_id"] = int(t.get("next_culture_id", 1)) + 1
    t["cultural_lineages"].append({
        "id": cid,
        "practice": practice,
        "founder_species": sp.get("id"),
        "origin_generation": generation,
        "last_generation": generation,
        "parent_id": parent_id,
        "status": "living",
        "carriers": [sp.get("id")],
    })
    t["cultural_lineages"] = t["cultural_lineages"][-MAX_CULTURAL_LINEAGES:]
    return cid


def _upsert_practice(
    world: dict[str, Any], sp: dict[str, Any], name: str, category: str, generation: int,
    strength: float, lineage_id: str | None = None, source: str = "innovation",
) -> tuple[dict[str, Any], bool]:
    techne = sp.setdefault("techne", {})
    rows = techne.setdefault("practices", [])
    for row in rows:
        if row.get("name") == name:
            row["strength"] = round(clamp(float(row.get("strength", 0)) * 0.76 + strength * 0.34, 0, 1), 4)
            row["last_generation"] = generation
            if lineage_id and not row.get("lineage_id"):
                row["lineage_id"] = lineage_id
            return row, False
    if lineage_id is None:
        lineage_id = _new_cultural_lineage(world, sp, name, generation)
    row = {
        "id": f"p-{stable_int('{}:{}:{}'.format(sp.get('id'), name, generation)) % 1000000:06d}",
        "name": name,
        "category": category,
        "origin_generation": generation,
        "last_generation": generation,
        "strength": round(clamp(strength, 0.08, 0.96), 4),
        "lineage_id": lineage_id,
        "source": source,
    }
    rows.append(row)
    techne["practices"] = rows[-MAX_PRACTICES:]
    stats = techne.setdefault("statistics", {})
    stats["innovations"] = int(stats.get("innovations", 0)) + (1 if source == "innovation" else 0)
    stats["received_practices"] = int(stats.get("received_practices", 0)) + (1 if source == "exchange" else 0)
    return row, True


def _site_kind(practice: str) -> str | None:
    return {
        "persistent nesting": "nest-site",
        "food caching": "cache-site",
        "route marking": "route-marker",
        "object selection": "tool-site",
        "object modification": "tool-site",
        "constructed shelter": "shelter",
        "water control": "waterwork",
        "resource tending": "tended-patch",
        "controlled combustion": "hearth",
        "compound tools": "workshop",
        "symbolic marking": "symbolic-site",
    }.get(practice)


def _create_site(world: dict[str, Any], sp: dict[str, Any], practice: dict[str, Any], generation: int, rng: random.Random) -> dict[str, Any] | None:
    kind = _site_kind(str(practice.get("name")))
    pos = _centroid(sp)
    if not kind or pos is None:
        return None
    t = ensure_world_techne(world)
    # A practice can create many real structures; PHYLUM stores one durable site
    # aggregate per region/practice rather than millions of individual artifacts.
    for s in t.get("sites", []):
        if s.get("species_id") == sp.get("id") and s.get("practice") == practice.get("name") and s.get("active"):
            try:
                if math.dist(s.get("position", pos), pos) <= 4.5:
                    s["last_generation"] = generation
                    s["durability"] = round(clamp(float(s.get("durability", 0.5)) + 0.02, 0, 1), 4)
                    return None
            except (TypeError, ValueError):
                pass
    sid = f"site-{int(t.get('next_site_id',1)):06d}"
    t["next_site_id"] = int(t.get("next_site_id", 1)) + 1
    base_durability = {
        "nest-site": 0.38, "cache-site": 0.28, "route-marker": 0.32, "tool-site": 0.48,
        "shelter": 0.65, "waterwork": 0.72, "tended-patch": 0.35, "hearth": 0.55,
        "workshop": 0.68, "symbolic-site": 0.76,
    }.get(kind, 0.4)
    site = {
        "id": sid, "kind": kind, "practice": practice.get("name"), "species_id": sp.get("id"),
        "culture_id": practice.get("lineage_id"), "origin_generation": generation, "last_generation": generation,
        "position": pos, "durability": round(clamp(base_durability + rng.uniform(-0.06, 0.08), 0.15, 0.92), 4),
        "active": True, "status": "active",
    }
    t["sites"].append(site)
    t["sites"] = t["sites"][-MAX_SITES:]
    sp["techne"].setdefault("statistics", {})["sites_created"] = int(sp["techne"].get("statistics", {}).get("sites_created", 0)) + 1
    return site


def _event(generation: int, kind: str, sp: dict[str, Any], text: str, **extra: Any) -> dict[str, Any]:
    row = {"generation": generation, "kind": kind, "subject": sp.get("id"), "text": text}
    row.update(extra)
    return row


def _candidate_innovations(sp: dict[str, Any], env: dict[str, Any]) -> list[tuple[str, str, float, float]]:
    t = sp.get("techne", {})
    c = t.get("capacities", {})
    nerve = _nerve(sp)
    manip = nerve.get("manipulation", {})
    soma = _soma(sp)
    repro = soma.get("reproduction", {})
    g = _genome(sp)
    innovation = float(c.get("innovation", 0))
    planning = float(nerve.get("architecture", {}).get("planning_horizon", 0))
    memory = float(nerve.get("architecture", {}).get("memory_capacity", 0))
    cooperation = float(nerve.get("social", {}).get("cooperation", 0))
    material = float(c.get("material_skill", 0))
    construction = float(c.get("construction", 0))
    language = float(c.get("language", 0))
    transmission = float(c.get("transmission", 0))
    tool = bool(manip.get("tool_capability", False))
    parental = float(repro.get("parental_care_score", 0))
    aquatic = float(g.get("aquatic", 0))
    engineering = float(g.get("engineering", 0))
    rows: list[tuple[str, str, float, float]] = []
    # name, category, readiness score, base probability. These are opportunities,
    # not a tech tree: no generation number unlocks anything.
    rows.append(("persistent nesting", "construction", clamp(construction * 0.42 + planning * 0.24 + parental * 0.20 + cooperation * 0.14, 0, 1), 0.010))
    rows.append(("food caching", "subsistence", clamp(planning * 0.34 + memory * 0.30 + material * 0.16 + innovation * 0.20, 0, 1), 0.007))
    rows.append(("route marking", "information", clamp(planning * 0.30 + memory * 0.22 + material * 0.18 + transmission * 0.30, 0, 1), 0.005))
    rows.append(("alarm dialect", "communication", clamp(language * 0.56 + cooperation * 0.22 + transmission * 0.22, 0, 1), 0.005))
    if tool:
        rows.append(("object selection", "material", clamp(material * 0.50 + planning * 0.20 + innovation * 0.30, 0, 1), 0.006))
        rows.append(("object modification", "material", clamp(material * 0.48 + planning * 0.25 + innovation * 0.27, 0, 1), 0.0025))
    if bool(manip.get("construction_capability", False)) or construction > 0.54:
        rows.append(("constructed shelter", "construction", clamp(construction * 0.54 + planning * 0.22 + cooperation * 0.24, 0, 1), 0.0035))
    rows.append(("resource tending", "subsistence", clamp(planning * 0.30 + cooperation * 0.26 + innovation * 0.20 + engineering * 0.24, 0, 1), 0.0014))
    if aquatic > 0.22 or float(env.get("moisture", 0.5)) > 0.58:
        rows.append(("water control", "construction", clamp(construction * 0.48 + engineering * 0.28 + planning * 0.24, 0, 1), 0.0009))
    if tool:
        rows.append(("compound tools", "material", clamp(material * 0.45 + planning * 0.30 + innovation * 0.25, 0, 1), 0.00035))
    rows.append(("symbolic marking", "information", clamp(language * 0.36 + planning * 0.28 + material * 0.18 + transmission * 0.18, 0, 1), 0.00028))
    # Controlled combustion is deliberately extreme and opportunity-dependent. A
    # dry/fire-prone environment helps; the simulation never grants it on schedule.
    fire_opportunity = clamp((0.58 - float(env.get("moisture", 0.5))) * 2.2 + (float(env.get("temperature", 0.5)) - 0.48), 0, 1)
    if aquatic < 0.30 and tool:
        rows.append(("controlled combustion", "energy", clamp(material * 0.28 + planning * 0.24 + innovation * 0.20 + engineering * 0.16 + fire_opportunity * 0.12, 0, 1), 0.00008))
    return rows


def _decay_practices(sp: dict[str, Any], generation: int, infection: float) -> list[str]:
    techne = sp.get("techne", {})
    transmission = float(techne.get("capacities", {}).get("transmission", 0))
    population = float(sp.get("population", 0))
    bottleneck = clamp((60.0 - population) / 60.0, 0, 1)
    retain = clamp(0.922 + transmission * 0.060 - bottleneck * 0.055 - infection * 0.018, 0.82, 0.995)
    kept = []
    lost = []
    for row in techne.get("practices", []):
        cp = dict(row)
        cp["strength"] = round(float(cp.get("strength", 0.3)) * retain, 4)
        if cp["strength"] >= 0.075:
            kept.append(cp)
        else:
            lost.append(str(cp.get("name", "practice")))
    techne["practices"] = kept[-MAX_PRACTICES:]
    stats = techne.setdefault("statistics", {})
    stats["lost_practices"] = int(stats.get("lost_practices", 0)) + len(lost)
    return lost


def _decay_sites(world: dict[str, Any], species_by_id: dict[str, dict[str, Any]], generation: int) -> list[dict[str, Any]]:
    t = ensure_world_techne(world)
    events: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for site in t.get("sites", []):
        row = dict(site)
        creator = species_by_id.get(str(row.get("species_id")))
        creator_alive = bool(creator and creator.get("extinct_generation") is None and float(creator.get("population", 0)) > 0)
        maintenance = creator_alive and str(row.get("practice")) in _practice_names(creator)
        if maintenance:
            row["durability"] = round(clamp(float(row.get("durability", 0.4)) * 0.995 + 0.004, 0, 1), 4)
            row["last_generation"] = generation
            row["active"] = True
            row["status"] = "active"
        else:
            row["durability"] = round(float(row.get("durability", 0.4)) * 0.985, 4)
            if row.get("active"):
                row["active"] = False
                row["status"] = "ruin"
                if creator:
                    events.append(_event(generation, "artifact", creator, f"A {row.get('kind','cultural')} site associated with {creator.get('name')} falls out of active use.", site_id=row.get("id")))
        if float(row.get("durability", 0)) >= 0.035:
            kept.append(row)
        else:
            archive = {k: row.get(k) for k in ("id", "kind", "practice", "species_id", "culture_id", "origin_generation", "last_generation", "position")}
            archive["lost_generation"] = generation
            t["archive"].append(archive)
    t["sites"] = kept[-MAX_SITES:]
    t["archive"] = t["archive"][-MAX_ARCHIVE:]
    return events


def _ranges_contact(a: dict[str, Any], b: dict[str, Any]) -> float:
    ra, rb = _cells(a), _cells(b)
    if not ra or not rb:
        return 0.0
    overlap = len(ra & rb)
    if overlap:
        return clamp(overlap / max(1, min(len(ra), len(rb))), 0, 1)
    # Adjacent ranges still permit observation/exchange.
    border = 0
    for x, y in ra:
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            if (x+dx, y+dy) in rb:
                border += 1
    return clamp(border / max(1, min(len(ra), len(rb))) * 0.55, 0, 0.55)


def finalize_techne_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    generation = int(world.get("generation", 0))
    seed = int(world.get("seed", 0))
    t = ensure_world_techne(world)
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    events = _decay_sites(world, by_id, generation)
    living = [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]

    for sp in living:
        techne = ensure_techne_schema(sp, seed, generation, by_id)
        techne["experience_generations"] = int(techne.get("experience_generations", 0)) + 1
        base = _base_capacities(sp)
        for key, val in base.items():
            techne["capacities"][key] = round(clamp(float(techne["capacities"].get(key, val)) * 0.88 + val * 0.12, 0, 1), 5)
        infection = max([float(v) for v in sp.get("infections", {}).values()] or [0.0])
        for lost in _decay_practices(sp, generation, infection):
            events.append(_event(generation, "knowledge_loss", sp, f"{sp.get('name')} loses the {lost} tradition."))

        names = _practice_names(sp)
        caps = techne.get("capacities", {})
        # Readiness must exceed the candidate threshold before random chance is even
        # considered. Advanced innovations therefore remain impossible for primitive
        # lineages even over arbitrarily many scheduled generations.
        for name, category, readiness, base_chance in _candidate_innovations(sp, env):
            if name in names:
                continue
            threshold = {
                "persistent nesting": 0.30, "food caching": 0.34, "route marking": 0.38, "alarm dialect": 0.40,
                "object selection": 0.48, "object modification": 0.61, "constructed shelter": 0.58,
                "resource tending": 0.64, "water control": 0.69, "compound tools": 0.80,
                "symbolic marking": 0.82, "controlled combustion": 0.88,
            }.get(name, 0.55)
            if readiness < threshold:
                continue
            chance = base_chance * (0.35 + readiness * 0.85)
            if rng.random() >= chance:
                continue
            practice, created = _upsert_practice(world, sp, name, category, generation, 0.34 + readiness * 0.42)
            if created:
                kind = "construction" if category == "construction" else "innovation"
                events.append(_event(generation, kind, sp, f"{sp.get('name')} establishes {name} as a persistent cultural practice.", practice=name, culture_id=practice.get("lineage_id")))
                site = _create_site(world, sp, practice, generation, rng)
                if site:
                    events.append(_event(generation, "artifact", sp, f"{sp.get('name')} leaves a persistent {site.get('kind')} associated with {name}.", site_id=site.get("id")))
                names.add(name)

        # Dialects drift independently of genes. The same species can therefore carry
        # cultural history that does not line up perfectly with its phylogeny.
        lang = float(caps.get("language", 0))
        trans = float(caps.get("transmission", 0))
        if lang > 0.43 and trans > 0.30 and rng.random() < 0.0015 + lang * 0.003:
            d = techne.setdefault("dialect", _dialect_seed(sp, seed))
            old = str(d.get("variant", "d-00000"))
            d["divergence"] = round(clamp(float(d.get("divergence", 0)) + 0.05 + lang * 0.04, 0, 1), 4)
            d["variant"] = f"d-{stable_int('{}:{}:{}'.format(old, sp.get('id'), generation)) % 100000:05d}"
            events.append(_event(generation, "language", sp, f"{sp.get('name')} develops a distinct signaling dialect."))

        # Strong practices occasionally produce a cultural descendant without a
        # biological speciation event. This is the cultural phylogeny.
        innovation = float(caps.get("innovation", 0))
        strong = [p for p in techne.get("practices", []) if float(p.get("strength", 0)) > 0.58 and p.get("lineage_id")]
        if innovation > 0.55 and strong and rng.random() < 0.0008 + innovation * 0.0016:
            src = rng.choice(strong)
            old_id = str(src.get("lineage_id"))
            new_id = _new_cultural_lineage(world, sp, str(src.get("name")), generation, parent_id=old_id)
            src["lineage_id"] = new_id
            src["strength"] = round(clamp(float(src.get("strength", 0.6)) * 0.82, 0, 1), 4)
            events.append(_event(generation, "culture", sp, f"A distinct cultural lineage of {src.get('name')} emerges within {sp.get('name')}.", parent_culture=old_id, culture_id=new_id))

        techne["modifiers"] = _modifiers(sp)
        pressures = techne.setdefault("selection_pressures", {})
        load = clamp(len(techne.get("practices", [])) / 12.0, 0, 1)
        pressures["culture"] = round(clamp(float(pressures.get("culture", 0)) * 0.90 + load * trans * 0.10, 0, 1), 5)
        pressures["construction"] = round(clamp(float(pressures.get("construction", 0)) * 0.90 + len([p for p in techne.get("practices", []) if p.get("category") == "construction"]) * 0.04, 0, 1), 5)
        pressures["communication"] = round(clamp(float(pressures.get("communication", 0)) * 0.90 + lang * load * 0.08, 0, 1), 5)

    # Cultural exchange can cross biological species boundaries when ranges touch.
    # It copies a practice's cultural lineage rather than inventing a new gene.
    for i, a in enumerate(living):
        for b in living[i+1:]:
            contact = _ranges_contact(a, b)
            if contact <= 0:
                continue
            for donor, receiver in ((a, b), (b, a)):
                rcaps = receiver.get("techne", {}).get("capacities", {})
                if float(rcaps.get("transmission", 0)) < 0.30:
                    continue
                donor_practices = [p for p in donor.get("techne", {}).get("practices", []) if float(p.get("strength", 0)) > 0.42]
                if not donor_practices:
                    continue
                if rng.random() >= (0.0015 + contact * 0.009) * (0.5 + float(rcaps.get("transmission", 0))):
                    continue
                src = rng.choice(donor_practices)
                if str(src.get("name")) in _practice_names(receiver):
                    continue
                row, created = _upsert_practice(world, receiver, str(src.get("name")), str(src.get("category", "tradition")), generation, float(src.get("strength", 0.4)) * 0.52, lineage_id=src.get("lineage_id"), source="exchange")
                if created:
                    events.append(_event(generation, "cultural_exchange", receiver, f"{receiver.get('name')} acquires {src.get('name')} through contact with {donor.get('name')}.", donor=donor.get("id"), culture_id=row.get("lineage_id")))

    # Update carrier lists and lineage status after all exchange/innovation.
    carriers: dict[str, set[str]] = {}
    for sp in living:
        for p in sp.get("techne", {}).get("practices", []):
            if p.get("lineage_id"):
                carriers.setdefault(str(p["lineage_id"]), set()).add(str(sp.get("id")))
    for line in t.get("cultural_lineages", []):
        cid = str(line.get("id"))
        rows = sorted(carriers.get(cid, set()))
        line["carriers"] = rows
        line["last_generation"] = generation if rows else int(line.get("last_generation", generation))
        line["status"] = "living" if rows else "extinct"
    t["statistics"] = {
        "active_sites": sum(bool(s.get("active")) for s in t.get("sites", [])),
        "ruins": sum(not bool(s.get("active")) for s in t.get("sites", [])),
        "archived_sites": len(t.get("archive", [])),
        "living_cultural_lineages": sum(l.get("status") == "living" for l in t.get("cultural_lineages", [])),
        "cultural_lineages_ever": len(t.get("cultural_lineages", [])),
        "practices": sum(len(s.get("techne", {}).get("practices", [])) for s in living),
    }
    return events


def techne_bias_descendant_genome(parent: dict[str, Any], child: dict[str, float], rng: random.Random, magnitude: float = 1.0) -> dict[str, float]:
    pressures = parent.get("techne", {}).get("selection_pressures", {})
    if not pressures:
        return child
    bounds = {"complexity": (0.0, 1.0), "sociality": (0.0, 1.0), "engineering": (0.0, 1.0), "sensory": (0.0, 1.0), "lifespan": (0.05, 1.0)}
    def nudge(key: str, pressure: float, scale: float) -> None:
        if key not in child or pressure <= 0:
            return
        lo, hi = bounds[key]
        child[key] = round(clamp(float(child[key]) + clamp(pressure, 0, 1) * scale * magnitude * rng.uniform(0.45, 1.0), lo, hi), 5)
    culture = float(pressures.get("culture", 0))
    construction = float(pressures.get("construction", 0))
    communication = float(pressures.get("communication", 0))
    # Gene-culture coevolution is intentionally weaker than NERVE selection. Culture
    # can reshape selection, but it cannot simply force a biological progression.
    nudge("complexity", culture + communication * 0.4, 0.0017)
    nudge("sociality", culture + communication * 0.5, 0.0020)
    nudge("engineering", construction + culture * 0.3, 0.0022)
    nudge("sensory", communication, 0.0012)
    nudge("lifespan", culture, 0.0009)
    return child


def validate_techne_state(sp: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    t = sp.get("techne")
    if not isinstance(t, dict):
        return [f"missing TECHNE state {sp.get('id')}"]
    if int(t.get("schema", 0)) != TECHNE_SCHEMA_VERSION:
        errors.append(f"TECHNE schema mismatch {sp.get('id')}")
    for key, val in t.get("capacities", {}).items():
        try:
            f = float(val)
        except (TypeError, ValueError):
            errors.append(f"invalid TECHNE capacity {key} {sp.get('id')}")
            continue
        if not 0 <= f <= 1:
            errors.append(f"TECHNE capacity out of bounds {key} {sp.get('id')}")
    if len(t.get("practices", [])) > MAX_PRACTICES:
        errors.append(f"TECHNE practice overflow {sp.get('id')}")
    for p in t.get("practices", []):
        if not 0 <= float(p.get("strength", 0)) <= 1:
            errors.append(f"TECHNE practice strength invalid {sp.get('id')}")
            break
    return errors


def validate_techne_world(world: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    t = world.get("techne")
    if not isinstance(t, dict):
        return ["missing TECHNE world state"]
    if int(t.get("schema", 0)) != TECHNE_SCHEMA_VERSION:
        errors.append("TECHNE world schema mismatch")
    if len(t.get("sites", [])) > MAX_SITES:
        errors.append("TECHNE site overflow")
    if len(t.get("archive", [])) > MAX_ARCHIVE:
        errors.append("TECHNE archive overflow")
    if len(t.get("cultural_lineages", [])) > MAX_CULTURAL_LINEAGES:
        errors.append("TECHNE cultural lineage overflow")
    ids = [s.get("id") for s in t.get("sites", [])]
    if len(ids) != len(set(ids)):
        errors.append("duplicate TECHNE site ids")
    return errors


def techne_catalog(world: dict[str, Any], species: list[dict[str, Any]]) -> dict[str, Any]:
    t = ensure_world_techne(world)
    living = []
    for sp in species:
        if sp.get("extinct_generation") is not None:
            continue
        techne = sp.get("techne", {})
        living.append({
            "id": sp.get("id"), "name": sp.get("name"), "population": round(float(sp.get("population", 0)), 2),
            "capacities": techne.get("capacities", {}), "dialect": techne.get("dialect", {}),
            "practices": techne.get("practices", []), "statistics": techne.get("statistics", {}),
        })
    return {"generation": int(world.get("generation", 0)), "statistics": t.get("statistics", {}), "lineages": living, "sites": t.get("sites", []), "cultural_lineages": t.get("cultural_lineages", [])}


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


def _bar(v: float, w: float = 150) -> float:
    return clamp(float(v), 0, 1) * w


def render_techne_svg(world: dict[str, Any], species: list[dict[str, Any]], output_path: Path) -> str:
    t = ensure_world_techne(world)
    live = sorted([s for s in species if s.get("extinct_generation") is None], key=lambda s: float(s.get("population", 0)), reverse=True)[:16]
    cols = 2; card_w = 690; card_h = 310; rows = max(1, math.ceil(len(live) / cols))
    W = 1480; H = 190 + rows * (card_h + 24)
    stats = t.get("statistics", {})
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         '<rect width="100%" height="100%" fill="#071014"/><style>text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;fill:#dce8e2}.m{fill:#738a84}.a{fill:#a7c3b7}.line{stroke:#263b38}.track{fill:#152724}.fill{fill:#8eb3a2}.site{fill:#b8c8a0}</style>',
         f'<text x="42" y="50" font-size="24" letter-spacing="5">PHYLUM / TECHNE CULTURAL RECORD</text>',
         f'<text x="42" y="80" class="m" font-size="11">GEN {int(world.get("generation",0)):06d} · inherited knowledge / material culture / archaeology</text>',
         f'<text x="42" y="118" class="a" font-size="12">{int(stats.get("living_cultural_lineages",0))} living cultural lineages · {int(stats.get("active_sites",0))} active sites · {int(stats.get("ruins",0))} ruins · {int(stats.get("practices",0))} practices</text>']
    for idx, sp in enumerate(live):
        x = 42 + (idx % cols) * (card_w + 26); y = 150 + (idx // cols) * (card_h + 24)
        techne = sp.get("techne", {}); c = techne.get("capacities", {}); practices = techne.get("practices", [])
        p.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="9" fill="#0b1719" stroke="#263b38"/>')
        p.append(f'<text x="{x+22}" y="{y+32}" font-size="16">{_esc(sp.get("name"))}</text><text x="{x+card_w-22}" y="{y+32}" class="m" text-anchor="end" font-size="11">{int(float(sp.get("population",0))):,} organisms</text>')
        metrics = [("STORAGE", c.get("cultural_storage",0)), ("INNOVATION",c.get("innovation",0)), ("MATERIAL",c.get("material_skill",0)), ("LANGUAGE",c.get("language",0))]
        for mi,(lab,val) in enumerate(metrics):
            yy=y+72+mi*34
            p.append(f'<text x="{x+22}" y="{yy}" class="m" font-size="10">{lab}</text><rect x="{x+112}" y="{yy-9}" width="150" height="10" rx="3" class="track"/><rect x="{x+112}" y="{yy-9}" width="{_bar(float(val)):.1f}" height="10" rx="3" class="fill"/><text x="{x+274}" y="{yy}" class="m" font-size="10">{float(val):.2f}</text>')
        d = techne.get("dialect", {})
        p.append(f'<text x="{x+330}" y="{y+72}" class="m" font-size="10">DIALECT</text><text x="{x+410}" y="{y+72}" font-size="10">{_esc(d.get("family","—"))} / {_esc(d.get("variant","—"))}</text>')
        p.append(f'<text x="{x+330}" y="{y+102}" class="m" font-size="10">PRACTICES</text>')
        for j,row in enumerate(practices[-7:]):
            p.append(f'<text x="{x+350}" y="{y+126+j*22}" font-size="10">• {_esc(row.get("name"))}</text><text x="{x+card_w-24}" y="{y+126+j*22}" class="m" text-anchor="end" font-size="9">{float(row.get("strength",0)):.2f}</text>')
        if not practices:
            p.append(f'<text x="{x+350}" y="{y+126}" class="m" font-size="10">no persistent material/cultural practice yet</text>')
        p.append(f'<text x="{x+22}" y="{y+278}" class="m" font-size="9">TECHNE state is aggregate culture, not a deterministic civilization tech tree.</text>')
    p.append('</svg>')
    text=''.join(p); output_path.parent.mkdir(parents=True,exist_ok=True); output_path.write_text(text,encoding='utf-8'); return text


def render_techne_assets(world: dict[str, Any], species: list[dict[str, Any]], root: Path) -> None:
    root = Path(root)
    svg = render_techne_svg(world, species, root / "renders" / "techne.svg")
    docs = root / "docs"; docs.mkdir(parents=True, exist_ok=True)
    (docs / "techne.svg").write_text(svg, encoding="utf-8")
    data = techne_catalog(world, species)
    (docs / "techne-data.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PHYLUM / TECHNE</title><style>body{{margin:0;background:#071014;color:#dce8e2;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}header{{padding:22px 28px;border-bottom:1px solid #263b38}}main{{padding:24px;max-width:1300px;margin:auto}}.muted{{color:#738a84}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:14px}}.card{{border:1px solid #263b38;background:#0b1719;border-radius:9px;padding:16px}}.site{{border-left:3px solid #8eb3a2;padding-left:10px;margin:8px 0}}input{{background:#0b1719;color:#dce8e2;border:1px solid #263b38;border-radius:6px;padding:9px;width:min(520px,95%)}}a{{color:#a7c3b7}}</style></head><body><header><b>PHYLUM / TECHNE</b><div class="muted">cultural inheritance · material traces · archaeology · generation {int(world.get("generation",0)):06d}</div></header><main><p><a href="index.html">← Observatory</a></p><input id="q" placeholder="filter cultures, practices, sites"><h2>Living cultures</h2><div id="grid" class="grid"></div><h2>Archaeological sites</h2><div id="sites"></div></main><script>const DATA={payload};const q=document.getElementById('q'),grid=document.getElementById('grid'),sites=document.getElementById('sites');function draw(){{const s=q.value.toLowerCase();grid.innerHTML=DATA.lineages.filter(x=>JSON.stringify(x).toLowerCase().includes(s)).map(x=>`<div class="card"><b>${{x.name}}</b><div class="muted">${{Math.round(x.population).toLocaleString()}} organisms · ${{x.dialect?.variant||'no dialect'}}</div><p>${{(x.practices||[]).map(p=>p.name).join(' · ')||'no persistent TECHNE practices yet'}}</p></div>`).join('');sites.innerHTML=DATA.sites.filter(x=>JSON.stringify(x).toLowerCase().includes(s)).slice().reverse().map(x=>`<div class="site"><b>${{x.kind}}</b> · ${{x.practice}} <span class="muted">${{x.status}} · gen ${{String(x.origin_generation).padStart(6,'0')}}</span></div>`).join('')||'<div class="muted">no archaeological sites yet</div>'}}q.addEventListener('input',draw);draw();</script></body></html>'''
    (docs / "techne.html").write_text(page, encoding="utf-8")
