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

SOCIUS_SCHEMA_VERSION = 1
MAX_GROUPS = 300
MAX_ARCHIVE = 700
MAX_RELATIONSHIPS = 600
MAX_LINEAGES = 900
MAX_NORMS = 8
MAX_GROUP_HISTORY = 14
MAX_TERRITORY = 80


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


def _centroid(cells: set[tuple[int, int]] | list[tuple[int, int]]) -> list[float] | None:
    rows = list(cells)
    if not rows:
        return None
    return [round(sum(x for x, _ in rows) / len(rows), 3), round(sum(y for _, y in rows) / len(rows), 3)]


def _species_centroid(sp: dict[str, Any]) -> list[float] | None:
    return _centroid(_cells(sp))


def _nerve(sp: dict[str, Any]) -> dict[str, Any]:
    return sp.get("nerve", {}) if isinstance(sp.get("nerve"), dict) else {}


def _techne(sp: dict[str, Any]) -> dict[str, Any]:
    return sp.get("techne", {}) if isinstance(sp.get("techne"), dict) else {}


def _soma(sp: dict[str, Any]) -> dict[str, Any]:
    return sp.get("soma", {}) if isinstance(sp.get("soma"), dict) else {}


def _genome(sp: dict[str, Any]) -> dict[str, float]:
    return {str(k): float(v) for k, v in sp.get("genome", {}).items() if isinstance(v, (int, float))}


def _base_capacities(sp: dict[str, Any]) -> dict[str, float]:
    n = _nerve(sp)
    t = _techne(sp)
    s = _soma(sp)
    g = _genome(sp)
    arch = n.get("architecture", {})
    social = n.get("social", {})
    temp = n.get("temperament", {})
    tc = t.get("capacities", {})
    repro = s.get("reproduction", {})
    behavior = s.get("behavior", {})
    neural = float(arch.get("neural_complexity", 0.05))
    memory = float(arch.get("memory_capacity", 0.05))
    planning = float(arch.get("planning_horizon", 0.0))
    cooperation = float(social.get("cooperation", 0.08))
    recognition = float(social.get("recognition", 0.05))
    reciprocity = float(social.get("reciprocity", 0.0))
    signal = float(social.get("signal_complexity", 0.05))
    sociality = float(g.get("sociality", 0.1))
    aggression = float(g.get("aggression", 0.1))
    transmission = float(tc.get("transmission", 0.0))
    storage = float(tc.get("cultural_storage", 0.0))
    parental = float(repro.get("parental_care_score", 0.0))
    territoriality = float(behavior.get("territoriality", 0.0))
    group_persistence = clamp(
        sociality * 0.22 + cooperation * 0.25 + recognition * 0.17 + memory * 0.10
        + transmission * 0.12 + parental * 0.08 + signal * 0.06,
        0, 1,
    )
    identity = clamp(recognition * 0.29 + signal * 0.20 + storage * 0.17 + transmission * 0.16 + sociality * 0.18, 0, 1)
    coordination = clamp(cooperation * 0.31 + signal * 0.23 + planning * 0.18 + neural * 0.13 + reciprocity * 0.15, 0, 1)
    norm_retention = clamp(transmission * 0.28 + storage * 0.24 + recognition * 0.16 + memory * 0.14 + cooperation * 0.18, 0, 1)
    tolerance = clamp(0.56 + cooperation * 0.22 + reciprocity * 0.18 - aggression * 0.36 - territoriality * 0.13, 0.04, 0.96)
    differentiation = clamp(identity * 0.28 + signal * 0.20 + storage * 0.22 + territoriality * 0.15 + planning * 0.15, 0, 1)
    leadership = clamp(planning * 0.28 + recognition * 0.21 + signal * 0.17 + memory * 0.17 + neural * 0.17, 0, 1)
    return {
        "group_persistence": round(group_persistence, 5),
        "identity": round(identity, 5),
        "coordination": round(coordination, 5),
        "norm_retention": round(norm_retention, 5),
        "tolerance": round(tolerance, 5),
        "differentiation": round(differentiation, 5),
        "leadership": round(leadership, 5),
    }


def _base_socius(sp: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SOCIUS_SCHEMA_VERSION,
        "capacities": _base_capacities(sp),
        "group_ids": [],
        "modifiers": {"demography": 1.0, "cultural_retention": 1.0, "migration": 1.0},
        "selection_pressures": {"cooperation": 0.0, "identity": 0.0, "tolerance": 0.0},
        "statistics": {"groups_formed": 0, "groups_lost": 0, "fissions": 0, "mergers": 0, "norms_formed": 0},
        "experience_generations": 0,
    }


def ensure_world_socius(world: dict[str, Any]) -> dict[str, Any]:
    s = world.setdefault("socius", {})
    if not isinstance(s, dict):
        world["socius"] = s = {}
    s["schema"] = SOCIUS_SCHEMA_VERSION
    s.setdefault("groups", [])
    s.setdefault("archive", [])
    s.setdefault("relationships", [])
    s.setdefault("group_lineages", [])
    s.setdefault("next_group_id", 1)
    s.setdefault("statistics", {})
    s["groups"] = [g for g in s.get("groups", []) if isinstance(g, dict)][-MAX_GROUPS:]
    s["archive"] = [g for g in s.get("archive", []) if isinstance(g, dict)][-MAX_ARCHIVE:]
    s["relationships"] = [r for r in s.get("relationships", []) if isinstance(r, dict)][-MAX_RELATIONSHIPS:]
    s["group_lineages"] = [r for r in s.get("group_lineages", []) if isinstance(r, dict)][-MAX_LINEAGES:]
    return s


def ensure_socius_schema(
    sp: dict[str, Any],
    seed: int,
    generation: int,
    species_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(sp.get("socius"), dict) or not sp.get("socius"):
        sp["socius"] = _base_socius(sp)
    soc = sp["socius"]
    soc["schema"] = SOCIUS_SCHEMA_VERSION
    base = _base_capacities(sp)
    soc.setdefault("capacities", {})
    for key, val in base.items():
        old = soc["capacities"].get(key)
        soc["capacities"][key] = round(float(old) * 0.86 + val * 0.14, 5) if isinstance(old, (int, float)) else val
    soc.setdefault("group_ids", [])
    soc["group_ids"] = [str(x) for x in soc.get("group_ids", [])][-24:]
    soc.setdefault("modifiers", {"demography": 1.0, "cultural_retention": 1.0, "migration": 1.0})
    soc.setdefault("selection_pressures", {"cooperation": 0.0, "identity": 0.0, "tolerance": 0.0})
    soc.setdefault("statistics", {"groups_formed": 0, "groups_lost": 0, "fissions": 0, "mergers": 0, "norms_formed": 0})
    soc.setdefault("experience_generations", 0)
    return soc


def _leadership_style(sp: dict[str, Any], capacities: dict[str, float]) -> str:
    g = _genome(sp)
    n = _nerve(sp)
    s = _soma(sp)
    arch = n.get("architecture", {})
    social = n.get("social", {})
    parental = float(s.get("reproduction", {}).get("parental_care_score", 0))
    aggression = float(g.get("aggression", 0))
    planning = float(arch.get("planning_horizon", 0))
    memory = float(arch.get("memory_capacity", 0))
    signal = float(social.get("signal_complexity", 0))
    coordination = float(capacities.get("coordination", 0))
    if aggression > 0.64 and coordination > 0.42:
        return "dominance-mediated"
    if planning + memory > 1.08 and float(capacities.get("leadership", 0)) > 0.48:
        return "experience-guided"
    if parental > 0.56 and float(social.get("recognition", 0)) > 0.50:
        return "kin-centered"
    if signal > 0.68 and coordination > 0.58:
        return "signal-led"
    if coordination > 0.68:
        return "distributed"
    return "diffuse"


def _group_name(sp: dict[str, Any], gid: str, centroid: list[float] | None) -> str:
    if centroid is None:
        zone = "range"
    else:
        x, y = centroid
        ew = "west" if x < GRID_COLS * 0.38 else "east" if x > GRID_COLS * 0.62 else "central"
        ns = "north" if y < GRID_ROWS * 0.38 else "south" if y > GRID_ROWS * 0.62 else "mid"
        zone = f"{ns}-{ew}"
    suffix = int(gid.split("-")[-1]) if gid.split("-")[-1].isdigit() else stable_int(gid) % 999
    return f"{zone} group {suffix}"


def _territory_partition(sp: dict[str, Any], groups: list[dict[str, Any]]) -> None:
    cells = sorted(_cells(sp))
    active = [g for g in groups if g.get("status") == "active"]
    if not active:
        return
    buckets: dict[str, list[tuple[int, int]]] = {str(g["id"]): [] for g in active}
    if len(active) == 1:
        buckets[str(active[0]["id"])] = cells
    else:
        for cell in cells:
            chosen = min(active, key=lambda g: stable_int(f"socius-territory:{g.get('id')}:{cell[0]}:{cell[1]}"))
            buckets[str(chosen["id"])].append(cell)
    for g in active:
        rows = buckets.get(str(g["id"]), [])[:MAX_TERRITORY]
        g["territory"] = [[x, y] for x, y in rows]
        g["centroid"] = _centroid(rows) or _species_centroid(sp)


def _create_group(
    world: dict[str, Any],
    sp: dict[str, Any],
    generation: int,
    rng: random.Random,
    parent_group_id: str | None = None,
    share: float | None = None,
) -> dict[str, Any]:
    ws = ensure_world_socius(world)
    soc = ensure_socius_schema(sp, int(world.get("seed", 0)), generation)
    gid = f"sg-{int(ws.get('next_group_id', 1)):06d}"
    ws["next_group_id"] = int(ws.get("next_group_id", 1)) + 1
    caps = soc.get("capacities", {})
    cohesion = clamp(float(caps.get("group_persistence", 0)) * 0.72 + float(caps.get("coordination", 0)) * 0.20 + rng.uniform(-0.05, 0.05), 0.08, 0.96)
    identity = clamp(float(caps.get("identity", 0)) * 0.78 + rng.uniform(-0.04, 0.05), 0.05, 0.96)
    tolerance = clamp(float(caps.get("tolerance", 0.5)) + rng.uniform(-0.08, 0.08), 0.03, 0.97)
    aggression = clamp(float(_genome(sp).get("aggression", 0.1)) * 0.72 + rng.uniform(-0.05, 0.05), 0.01, 0.96)
    cells = _cells(sp)
    centroid = _centroid(cells)
    if share is None:
        share = clamp(0.22 + float(caps.get("group_persistence", 0)) * 0.42 + rng.uniform(-0.05, 0.05), 0.16, 0.74)
    practices = sorted(_techne(sp).get("practices", []), key=lambda x: float(x.get("strength", 0)), reverse=True)
    group = {
        "id": gid,
        "species_id": sp.get("id"),
        "name": _group_name(sp, gid, centroid),
        "origin_generation": generation,
        "last_generation": generation,
        "parent_group_id": parent_group_id,
        "status": "active",
        "population_share": round(float(share), 5),
        "cohesion": round(cohesion, 5),
        "identity": round(identity, 5),
        "tolerance": round(tolerance, 5),
        "aggression": round(aggression, 5),
        "coordination": round(float(caps.get("coordination", 0)), 5),
        "leadership": _leadership_style(sp, caps),
        "norms": [],
        "cultural_practices": [str(p.get("name")) for p in practices[:5]],
        "territory": [],
        "centroid": centroid,
        "history": [{"generation": generation, "kind": "origin"}],
    }
    ws["groups"].append(group)
    ws["groups"] = ws["groups"][-MAX_GROUPS:]
    ws["group_lineages"].append({"group_id": gid, "species_id": sp.get("id"), "parent_group_id": parent_group_id, "origin_generation": generation})
    ws["group_lineages"] = ws["group_lineages"][-MAX_LINEAGES:]
    soc["group_ids"].append(gid)
    soc["group_ids"] = soc["group_ids"][-24:]
    stats = soc.setdefault("statistics", {})
    stats["groups_formed"] = int(stats.get("groups_formed", 0)) + 1
    return group


def _archive_group(world: dict[str, Any], sp: dict[str, Any], group: dict[str, Any], generation: int, reason: str) -> None:
    ws = ensure_world_socius(world)
    group["status"] = "collapsed"
    group["collapsed_generation"] = generation
    group["collapse_reason"] = reason
    group.setdefault("history", []).append({"generation": generation, "kind": "collapse", "reason": reason})
    archive = copy.deepcopy(group)
    ws["archive"].append(archive)
    ws["archive"] = ws["archive"][-MAX_ARCHIVE:]
    ws["groups"] = [g for g in ws.get("groups", []) if g.get("id") != group.get("id")]
    soc = sp.get("socius", {})
    soc["group_ids"] = [x for x in soc.get("group_ids", []) if x != group.get("id")]
    stats = soc.setdefault("statistics", {})
    stats["groups_lost"] = int(stats.get("groups_lost", 0)) + 1


def _candidate_norms(sp: dict[str, Any], group: dict[str, Any]) -> list[str]:
    n = _nerve(sp)
    t = _techne(sp)
    s = _soma(sp)
    out: list[str] = []
    social = n.get("social", {})
    behavior = s.get("behavior", {})
    repro = s.get("reproduction", {})
    practices = {str(p.get("name")) for p in t.get("practices", [])}
    if float(social.get("signal_complexity", 0)) > 0.42:
        out.append("shared alarm response")
    if float(social.get("cooperation", 0)) > 0.48:
        out.append("cooperative foraging")
    if float(repro.get("parental_care_score", 0)) > 0.34:
        out.append("juvenile provisioning")
    if float(behavior.get("territoriality", 0)) > 0.42:
        out.append("boundary recognition")
    if "food caching" in practices:
        out.append("cache sharing")
    if any(p in practices for p in ("persistent nesting", "constructed shelter", "water control")):
        out.append("site maintenance")
    if float(behavior.get("migration_tendency", 0)) > 0.42:
        out.append("route following")
    if float(social.get("teaching", 0)) > 0.28:
        out.append("tradition teaching")
    return out


def _update_norms(sp: dict[str, Any], group: dict[str, Any], generation: int, rng: random.Random) -> list[dict[str, Any]]:
    soc = sp.get("socius", {})
    retention = float(soc.get("capacities", {}).get("norm_retention", 0))
    existing = []
    lost: list[dict[str, Any]] = []
    for row in group.get("norms", []):
        cp = dict(row)
        cp["strength"] = round(float(cp.get("strength", 0.3)) * clamp(0.94 + retention * 0.05, 0.90, 0.995), 4)
        if cp["strength"] >= 0.075:
            existing.append(cp)
        else:
            lost.append(cp)
    group["norms"] = existing[-MAX_NORMS:]
    if retention > 0.38 and len(group["norms"]) < MAX_NORMS:
        names = {str(n.get("name")) for n in group["norms"]}
        candidates = [x for x in _candidate_norms(sp, group) if x not in names]
        chance = 0.010 + max(0.0, retention - 0.38) * 0.045 + float(group.get("cohesion", 0)) * 0.008
        if candidates and rng.random() < chance:
            name = candidates[int(rng.random() * len(candidates)) % len(candidates)]
            group["norms"].append({"name": name, "origin_generation": generation, "strength": round(clamp(0.28 + retention * 0.44, 0.2, 0.82), 4)})
            sp["socius"].setdefault("statistics", {})["norms_formed"] = int(sp["socius"].get("statistics", {}).get("norms_formed", 0)) + 1
            return [{"kind": "social_norm", "name": name, "formed": True}]
    return [{"kind": "social_norm", "name": str(x.get("name")), "formed": False} for x in lost]


def _territory_set(group: dict[str, Any]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for row in group.get("territory", []):
        if isinstance(row, (list, tuple)) and len(row) == 2:
            try:
                out.add((int(row[0]), int(row[1])))
            except (TypeError, ValueError):
                pass
    return out


def _contact_strength(a: dict[str, Any], b: dict[str, Any]) -> float:
    ra, rb = _territory_set(a), _territory_set(b)
    if not ra or not rb:
        ca, cb = a.get("centroid"), b.get("centroid")
        if not ca or not cb:
            return 0.0
        d = math.hypot(float(ca[0]) - float(cb[0]), float(ca[1]) - float(cb[1]))
        return clamp((6.0 - d) / 6.0, 0, 0.35)
    overlap = len(ra & rb)
    if overlap:
        return clamp(overlap / max(1, min(len(ra), len(rb))), 0, 1)
    border = 0
    for x, y in ra:
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            if (x + dx, y + dy) in rb:
                border += 1
    return clamp(border / max(1, min(len(ra), len(rb))) * 0.55, 0, 0.55)


def _relation_label(value: float) -> str:
    if value <= -0.60: return "antagonistic"
    if value <= -0.28: return "competitive"
    if value <= -0.08: return "wary"
    if value < 0.18: return "neutral"
    if value < 0.46: return "tolerant"
    if value < 0.72: return "cooperative"
    return "bonded"


def _ecology_bias(a: dict[str, Any], b: dict[str, Any], interactions: list[dict[str, Any]]) -> float:
    aid, bid = str(a.get("species_id")), str(b.get("species_id"))
    bias = 0.0
    for row in interactions:
        src, dst = str(row.get("source")), str(row.get("target"))
        if {src, dst} != {aid, bid}:
            continue
        strength = clamp(float(row.get("strength", 0)), 0, 1)
        if row.get("type") == "predation": bias -= 0.70 * strength
        elif row.get("type") == "competition": bias -= 0.42 * strength
        elif row.get("type") in {"mutualism", "symbiosis"}: bias += 0.42 * strength
    return clamp(bias, -0.8, 0.6)


def _upsert_relationship(
    world: dict[str, Any],
    a: dict[str, Any],
    b: dict[str, Any],
    interactions: list[dict[str, Any]],
    generation: int,
    contact: float,
) -> tuple[dict[str, Any], bool]:
    ws = ensure_world_socius(world)
    aid, bid = sorted((str(a.get("id")), str(b.get("id"))))
    existing = None
    for r in ws.get("relationships", []):
        if str(r.get("a")) == aid and str(r.get("b")) == bid:
            existing = r
            break
    ecology = _ecology_bias(a, b, interactions)
    mutual_tolerance = (float(a.get("tolerance", 0.5)) + float(b.get("tolerance", 0.5))) / 2
    cohesion = (float(a.get("cohesion", 0)) + float(b.get("cohesion", 0))) / 2
    aggression = (float(a.get("aggression", 0)) + float(b.get("aggression", 0))) / 2
    same_species = str(a.get("species_id")) == str(b.get("species_id"))
    target = (mutual_tolerance - 0.50) * 0.75 + cohesion * 0.12 - aggression * 0.38 + ecology
    if same_species:
        target += 0.10
    target *= 0.45 + contact * 0.55
    target = clamp(target, -1, 1)
    if existing is None:
        value = target * 0.42
        existing = {"a": aid, "b": bid, "value": round(value, 5), "label": _relation_label(value), "started_generation": generation, "last_generation": generation, "contact": round(contact, 4), "duration": 1}
        ws["relationships"].append(existing)
        changed = abs(value) >= 0.18
    else:
        old_label = str(existing.get("label", "neutral"))
        old = float(existing.get("value", 0))
        value = clamp(old * 0.84 + target * 0.16, -1, 1)
        existing.update({"value": round(value, 5), "label": _relation_label(value), "last_generation": generation, "contact": round(contact, 4), "duration": int(existing.get("duration", 0)) + 1})
        changed = old_label != existing["label"] and abs(value - old) >= 0.04
    ws["relationships"] = sorted(ws["relationships"], key=lambda x: int(x.get("last_generation", 0)))[-MAX_RELATIONSHIPS:]
    return existing, changed


def _event(generation: int, kind: str, sp: dict[str, Any] | None, text: str, **extra: Any) -> dict[str, Any]:
    row = {"generation": generation, "kind": kind, "subject": sp.get("id") if sp else "world", "text": text}
    row.update(extra)
    return row


def prepare_socius_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    ws = ensure_world_socius(world)
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    for sp in species:
        ensure_socius_schema(sp, int(world.get("seed", 0)), int(world.get("generation", 0)), by_id)
    active_by_species: dict[str, list[dict[str, Any]]] = {}
    for g in ws.get("groups", []):
        if g.get("status") == "active":
            active_by_species.setdefault(str(g.get("species_id")), []).append(g)
    for sp in species:
        soc = sp.get("socius", {})
        groups = active_by_species.get(str(sp.get("id")), [])
        coverage = clamp(sum(float(g.get("population_share", 0)) for g in groups), 0, 0.95)
        cohesion = sum(float(g.get("cohesion", 0)) * float(g.get("population_share", 0)) for g in groups)
        coord = sum(float(g.get("coordination", 0)) * float(g.get("population_share", 0)) for g in groups)
        conflict = 0.0
        gids = {str(g.get("id")) for g in groups}
        for rel in ws.get("relationships", []):
            if str(rel.get("a")) in gids or str(rel.get("b")) in gids:
                conflict += max(0.0, -float(rel.get("value", 0))) * float(rel.get("contact", 0))
        benefit = clamp((cohesion + coord) * 0.5, 0, 1)
        soc["modifiers"] = {
            "demography": round(clamp(1.0 + benefit * 0.008 - conflict * 0.005, 0.985, 1.012), 5),
            "cultural_retention": round(clamp(1.0 + coverage * float(soc.get("capacities", {}).get("norm_retention", 0)) * 0.025, 1.0, 1.025), 5),
            "migration": round(clamp(1.0 - coverage * 0.018 + conflict * 0.012, 0.98, 1.03), 5),
        }
    return []


def apply_socius_feedback(world: dict[str, Any], species: list[dict[str, Any]]) -> None:
    # Deliberately weak. SOCIUS may alter demographic outcomes, but social organization
    # is never a free evolutionary upgrade and cannot overpower ecology or disease.
    for sp in species:
        if sp.get("extinct_generation") is not None or float(sp.get("population", 0)) <= 0:
            continue
        mult = clamp(float(sp.get("socius", {}).get("modifiers", {}).get("demography", 1.0)), 0.985, 1.012)
        sp["population"] = round(max(0.0, float(sp.get("population", 0)) * mult), 3)
        sp["peak_population"] = max(float(sp.get("peak_population", 0)), float(sp.get("population", 0)))


def finalize_socius_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    generation = int(world.get("generation", 0))
    seed = int(world.get("seed", 0))
    ws = ensure_world_socius(world)
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    events: list[dict[str, Any]] = []
    living = [sp for sp in species if sp.get("extinct_generation") is None and float(sp.get("population", 0)) > 0]

    # Cull groups whose biological lineage no longer exists.
    for group in list(ws.get("groups", [])):
        sp = by_id.get(str(group.get("species_id")))
        if not sp or sp.get("extinct_generation") is not None or float(sp.get("population", 0)) <= 0:
            if sp:
                _archive_group(world, sp, group, generation, "biological extinction")
            else:
                ws["groups"].remove(group)
            continue

    for sp in living:
        soc = ensure_socius_schema(sp, seed, generation, by_id)
        soc["experience_generations"] = int(soc.get("experience_generations", 0)) + 1
        base = _base_capacities(sp)
        for key, val in base.items():
            soc["capacities"][key] = round(clamp(float(soc["capacities"].get(key, val)) * 0.90 + val * 0.10, 0, 1), 5)
        groups = [g for g in ws.get("groups", []) if g.get("status") == "active" and str(g.get("species_id")) == str(sp.get("id"))]
        readiness = float(soc.get("capacities", {}).get("group_persistence", 0))
        population = float(sp.get("population", 0))

        # Group formation is opportunity-gated. Migration never invents a group and
        # primitive lineages may remain non-grouped forever.
        if not groups and readiness >= 0.42 and population >= 80:
            chance = 0.006 + max(0.0, readiness - 0.42) * 0.050
            if rng.random() < chance:
                group = _create_group(world, sp, generation, rng)
                groups = [group]
                events.append(_event(generation, "group_formation", sp, f"{sp.get('name')} forms a persistent social group.", group_id=group.get("id")))

        # Update active group traits and cultural identities.
        groups = [g for g in ws.get("groups", []) if g.get("status") == "active" and str(g.get("species_id")) == str(sp.get("id"))]
        if groups:
            desired_total = clamp(0.28 + readiness * 0.60, 0.28, 0.92)
            each = desired_total / len(groups)
            practices = sorted(_techne(sp).get("practices", []), key=lambda x: float(x.get("strength", 0)), reverse=True)
            for group in groups:
                group["population_share"] = round(clamp(float(group.get("population_share", each)) * 0.88 + each * 0.12, 0.07, 0.86), 5)
                group["cohesion"] = round(clamp(float(group.get("cohesion", 0.3)) * 0.92 + readiness * 0.05 + float(soc["capacities"].get("coordination", 0)) * 0.03, 0.03, 0.98), 5)
                group["identity"] = round(clamp(float(group.get("identity", 0.2)) * 0.94 + float(soc["capacities"].get("identity", 0)) * 0.06, 0.03, 0.98), 5)
                group["coordination"] = round(float(soc["capacities"].get("coordination", 0)), 5)
                group["leadership"] = _leadership_style(sp, soc["capacities"])
                group["last_generation"] = generation
                group["cultural_practices"] = [str(p.get("name")) for p in practices[:5]]
                norm_changes = _update_norms(sp, group, generation, rng)
                for change in norm_changes:
                    if change.get("formed"):
                        events.append(_event(generation, "social_norm", sp, f"{group.get('name')} establishes a persistent norm of {change.get('name')}.", group_id=group.get("id")))
                group["history"] = [x for x in group.get("history", []) if isinstance(x, dict)][-MAX_GROUP_HISTORY:]

            _territory_partition(sp, groups)

            # Fission: stable identity can create multiple social lineages before biological speciation.
            differentiation = float(soc["capacities"].get("differentiation", 0))
            if len(groups) < 8 and population > 240 and differentiation > 0.52:
                largest = max(groups, key=lambda g: float(g.get("population_share", 0)))
                fission_chance = 0.0015 + max(0.0, differentiation - 0.52) * 0.018
                if float(largest.get("population_share", 0)) > 0.30 and rng.random() < fission_chance:
                    old_share = float(largest.get("population_share", 0))
                    child_share = old_share * clamp(0.30 + rng.random() * 0.18, 0.30, 0.48)
                    largest["population_share"] = round(old_share - child_share, 5)
                    child = _create_group(world, sp, generation, rng, str(largest.get("id")), child_share)
                    child["identity"] = round(clamp(float(largest.get("identity", 0.4)) + rng.uniform(-0.05, 0.08), 0.04, 0.98), 5)
                    child["tolerance"] = round(clamp(float(largest.get("tolerance", 0.5)) + rng.uniform(-0.08, 0.06), 0.03, 0.97), 5)
                    largest.setdefault("history", []).append({"generation": generation, "kind": "fission", "child_group_id": child.get("id")})
                    soc["statistics"]["fissions"] = int(soc["statistics"].get("fissions", 0)) + 1
                    events.append(_event(generation, "group_fission", sp, f"{largest.get('name')} divides and {child.get('name')} becomes a distinct social lineage.", group_id=child.get("id")))

            # Collapse can destroy a social lineage without killing the species.
            infection = max([float(v) for v in sp.get("infections", {}).values()] or [0.0])
            bottleneck = clamp((120.0 - population) / 120.0, 0, 1)
            for group in list(groups):
                fragility = clamp((0.34 - float(group.get("cohesion", 0))) * 1.4 + bottleneck * 0.38 + infection * 0.18, 0, 0.75)
                if fragility > 0.18 and rng.random() < fragility * 0.014:
                    _archive_group(world, sp, group, generation, "social fragmentation")
                    events.append(_event(generation, "social_collapse", sp, f"{group.get('name')} fragments while {sp.get('name')} survives biologically.", group_id=group.get("id")))

    # Repartition after any fission/collapse.
    for sp in living:
        groups = [g for g in ws.get("groups", []) if g.get("status") == "active" and str(g.get("species_id")) == str(sp.get("id"))]
        if groups:
            _territory_partition(sp, groups)

    # Persistent relationships are group-to-group, not species-wide abstractions.
    active = [g for g in ws.get("groups", []) if g.get("status") == "active"]
    for i, a in enumerate(active):
        for b in active[i+1:]:
            contact = _contact_strength(a, b)
            if contact < 0.04:
                continue
            rel, changed = _upsert_relationship(world, a, b, interactions, generation, contact)
            if changed and abs(float(rel.get("value", 0))) >= 0.28:
                spa = by_id.get(str(a.get("species_id")))
                spb = by_id.get(str(b.get("species_id")))
                an = a.get("name", a.get("id")); bn = b.get("name", b.get("id"))
                events.append(_event(generation, "social_relation", spa, f"{an} and {bn} enter a {rel.get('label')} relationship.", group_a=a.get("id"), group_b=b.get("id"), relation=rel.get("label"), other_species_id=spb.get("id") if spb else None))

    # Relationship memory fades slowly when groups no longer meet, instead of vanishing instantly.
    active_ids = {str(g.get("id")) for g in ws.get("groups", []) if g.get("status") == "active"}
    kept: list[dict[str, Any]] = []
    for rel in ws.get("relationships", []):
        if str(rel.get("a")) not in active_ids or str(rel.get("b")) not in active_ids:
            continue
        if int(rel.get("last_generation", generation)) < generation:
            rel["value"] = round(float(rel.get("value", 0)) * 0.992, 5)
            rel["label"] = _relation_label(float(rel.get("value", 0)))
        kept.append(rel)
    ws["relationships"] = kept[-MAX_RELATIONSHIPS:]
    stats = ws.setdefault("statistics", {})
    stats.update({
        "active_groups": len(ws.get("groups", [])),
        "archived_groups": len(ws.get("archive", [])),
        "relationships": len(ws.get("relationships", [])),
        "norms": sum(len(g.get("norms", [])) for g in ws.get("groups", [])),
    })
    return events


def validate_socius_state(sp: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    soc = sp.get("socius")
    if not isinstance(soc, dict):
        return [f"missing socius {sp.get('id')}"]
    if int(soc.get("schema", 0)) != SOCIUS_SCHEMA_VERSION:
        errors.append(f"socius schema {sp.get('id')}")
    caps = soc.get("capacities", {})
    for key in ("group_persistence", "identity", "coordination", "norm_retention", "tolerance", "differentiation", "leadership"):
        val = float(caps.get(key, -1))
        if not 0 <= val <= 1:
            errors.append(f"socius capacity {key} {sp.get('id')}")
    if len(soc.get("group_ids", [])) > 24:
        errors.append(f"too many socius group ids {sp.get('id')}")
    dm = float(soc.get("modifiers", {}).get("demography", 1.0))
    if not 0.98 <= dm <= 1.02:
        errors.append(f"socius demography modifier {sp.get('id')}")
    return errors


def validate_socius_world(world: dict[str, Any]) -> list[str]:
    ws = world.get("socius")
    if not isinstance(ws, dict):
        return ["missing world socius"]
    errors: list[str] = []
    if int(ws.get("schema", 0)) != SOCIUS_SCHEMA_VERSION:
        errors.append("world socius schema")
    groups = ws.get("groups", [])
    ids = [str(g.get("id")) for g in groups]
    if len(ids) != len(set(ids)):
        errors.append("duplicate social group ids")
    if len(groups) > MAX_GROUPS:
        errors.append("too many social groups")
    if len(ws.get("archive", [])) > MAX_ARCHIVE:
        errors.append("social archive overflow")
    if len(ws.get("relationships", [])) > MAX_RELATIONSHIPS:
        errors.append("social relationships overflow")
    for g in groups:
        if not 0 <= float(g.get("population_share", 0)) <= 1:
            errors.append(f"bad group share {g.get('id')}")
        if len(g.get("norms", [])) > MAX_NORMS:
            errors.append(f"too many norms {g.get('id')}")
        if len(g.get("territory", [])) > MAX_TERRITORY:
            errors.append(f"group territory overflow {g.get('id')}")
    return errors


def socius_catalog(world: dict[str, Any], species: list[dict[str, Any]]) -> dict[str, Any]:
    ws = ensure_world_socius(world)
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    groups = []
    for g in ws.get("groups", []):
        sp = by_id.get(str(g.get("species_id")))
        groups.append({
            "id": g.get("id"), "name": g.get("name"), "species_id": g.get("species_id"),
            "species_name": sp.get("name") if sp else None, "population_share": g.get("population_share"),
            "cohesion": g.get("cohesion"), "identity": g.get("identity"), "leadership": g.get("leadership"),
            "norms": [n.get("name") for n in g.get("norms", [])], "practices": g.get("cultural_practices", []),
            "origin_generation": g.get("origin_generation"), "parent_group_id": g.get("parent_group_id"),
        })
    return {
        "generation": int(world.get("generation", 0)),
        "active_groups": len(groups),
        "archived_groups": len(ws.get("archive", [])),
        "relationships": copy.deepcopy(ws.get("relationships", [])),
        "groups": groups,
        "statistics": copy.deepcopy(ws.get("statistics", {})),
    }


def _esc(v: Any) -> str:
    return html.escape(str(v), quote=True)


def render_socius_svg(world: dict[str, Any], species: list[dict[str, Any]], output_path: Path) -> str:
    ws = ensure_world_socius(world)
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    groups = [g for g in ws.get("groups", []) if g.get("status") == "active"]
    width = 1500
    height = max(700, 210 + max(1, len(groups)) * 82)
    parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="PHYLUM SOCIUS social lineage record">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#050b0d"/><stop offset="1" stop-color="#0c1416"/></linearGradient><style>
text{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#d8e3df}} .muted{{fill:#728983}} .tiny{{font-size:11px}} .small{{font-size:13px}} .label{{font-size:12px;letter-spacing:1.8px}} .hair{{stroke:#243536;stroke-width:1}} .card{{fill:#0a1316;stroke:#233638}}
</style></defs><rect width="100%" height="100%" fill="url(#bg)"/>
<text x="54" y="54" font-size="25" letter-spacing="5">SOCIUS / SOCIAL LINEAGES</text><text x="54" y="82" class="small muted">GEN {int(world.get('generation',0)):06d} · {len(groups)} ACTIVE GROUPS · {len(ws.get('relationships',[]))} RELATIONSHIPS · {len(ws.get('archive',[]))} ARCHIVED GROUPS</text>
''']
    if not groups:
        parts.append('<rect x="54" y="126" width="1392" height="420" rx="12" class="card"/><text x="750" y="318" text-anchor="middle" font-size="22" fill="#9bb0aa">NO PERSISTENT SOCIAL GROUPS YET</text><text x="750" y="353" text-anchor="middle" class="small muted">SOCIUS is active. Group formation remains gated by cognition, cooperation, recognition, population and culture.</text>')
    else:
        y = 136
        for g in groups:
            sp = by_id.get(str(g.get("species_id")), {})
            norms = ", ".join(str(n.get("name")) for n in g.get("norms", [])[:3]) or "none recorded"
            practices = ", ".join(str(x) for x in g.get("cultural_practices", [])[:3]) or "none"
            parts.append(f'<rect x="54" y="{y}" width="1392" height="64" rx="8" class="card"/>')
            parts.append(f'<text x="78" y="{y+23}" class="small">{_esc(g.get("name"))}</text><text x="78" y="{y+43}" class="tiny muted">{_esc(sp.get("name","unknown lineage"))} · {_esc(g.get("leadership","diffuse"))} · origin {int(g.get("origin_generation",0)):06d}</text>')
            parts.append(f'<text x="560" y="{y+23}" class="tiny muted">SHARE</text><text x="560" y="{y+44}" class="small">{float(g.get("population_share",0))*100:.1f}%</text>')
            parts.append(f'<text x="680" y="{y+23}" class="tiny muted">COHESION</text><text x="680" y="{y+44}" class="small">{float(g.get("cohesion",0)):.2f}</text>')
            parts.append(f'<text x="790" y="{y+23}" class="tiny muted">IDENTITY</text><text x="790" y="{y+44}" class="small">{float(g.get("identity",0)):.2f}</text>')
            parts.append(f'<text x="910" y="{y+23}" class="tiny muted">NORMS</text><text x="910" y="{y+44}" class="tiny">{_esc(norms)[:50]}</text>')
            parts.append(f'<text x="1180" y="{y+23}" class="tiny muted">CULTURE</text><text x="1180" y="{y+44}" class="tiny">{_esc(practices)[:34]}</text>')
            y += 82
    parts.append('</svg>')
    svg = ''.join(parts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return svg


def render_socius_assets(world: dict[str, Any], species: list[dict[str, Any]], root: Path) -> None:
    root = Path(root)
    renders = root / "renders"
    docs = root / "docs"
    renders.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)
    svg = render_socius_svg(world, species, renders / "socius.svg")
    (docs / "socius.svg").write_text(svg, encoding="utf-8")
    data = socius_catalog(world, species)
    (docs / "socius-data.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
