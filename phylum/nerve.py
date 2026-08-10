from __future__ import annotations

import copy
import html
import json
import math
import random
import shutil
from pathlib import Path
from typing import Any

from .constants import GRID_COLS, GRID_ROWS
from .utils import clamp, stable_int

NERVE_SCHEMA_VERSION = 1
MAX_MEMORIES = 28
MAX_TRADITIONS = 12
MAX_REPERTOIRE = 18


def _genome(sp: dict[str, Any]) -> dict[str, float]:
    return {str(k): float(v) for k, v in sp.get("genome", {}).items() if isinstance(v, (int, float))}


def _role(sp: dict[str, Any]) -> str:
    return str(sp.get("ecology", {}).get("role", "producer"))


def _cells(sp: dict[str, Any]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for item in sp.get("range", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                x, y = int(item[0]), int(item[1])
            except (TypeError, ValueError):
                continue
            if 0 <= x < GRID_COLS and 0 <= y < GRID_ROWS:
                out.append((x, y))
    return sorted(set(out))


def _centroid(sp: dict[str, Any]) -> list[float] | None:
    rows = _cells(sp)
    if not rows:
        return None
    return [round(sum(x for x, _ in rows) / len(rows), 3), round(sum(y for _, y in rows) / len(rows), 3)]


def _architecture_name(score: float) -> str:
    if score < 0.18:
        return "stimulus-net"
    if score < 0.34:
        return "diffuse-nerve-net"
    if score < 0.52:
        return "nerve-cord"
    if score < 0.70:
        return "ganglionic"
    if score < 0.86:
        return "centralized"
    return "integrative"


def _initial_repertoire(sp: dict[str, Any], neural: float, social: float) -> list[dict[str, Any]]:
    role = _role(sp)
    soma = sp.get("soma", {})
    behavior = soma.get("behavior", {})
    rows: list[dict[str, Any]] = [
        {"name": "resource-seeking", "kind": "inherited", "strength": round(clamp(0.42 + neural * 0.25, 0, 1), 4)},
        {"name": "threat-withdrawal", "kind": "inherited", "strength": round(clamp(0.35 + neural * 0.32, 0, 1), 4)},
    ]
    if float(behavior.get("migration_tendency", 0)) > 0.36:
        rows.append({"name": "range-exploration", "kind": "inherited", "strength": round(0.35 + neural * 0.25, 4)})
    if float(behavior.get("territoriality", 0)) > 0.35:
        rows.append({"name": "territory-defense", "kind": "inherited", "strength": round(0.32 + neural * 0.24, 4)})
    if social > 0.42:
        rows.append({"name": "group-cohesion", "kind": "inherited", "strength": round(clamp(0.28 + social * 0.45, 0, 1), 4)})
    if role == "predator":
        rows.append({"name": "prey-tracking", "kind": "inherited", "strength": round(clamp(0.34 + neural * 0.42, 0, 1), 4)})
    elif role in {"grazer", "omnivore"}:
        rows.append({"name": "patch-foraging", "kind": "inherited", "strength": round(clamp(0.38 + neural * 0.32, 0, 1), 4)})
    return rows[:MAX_REPERTOIRE]


def _base_nerve(sp: dict[str, Any], seed: int) -> dict[str, Any]:
    g = _genome(sp)
    soma = sp.get("soma", {})
    body = soma.get("body_plan", {})
    physiology = soma.get("physiology", {})
    behavior = soma.get("behavior", {})
    senses = list(dict.fromkeys(str(x) for x in body.get("senses", ["chemical"])))
    social = clamp(float(g.get("sociality", 0.2)), 0, 1)
    complexity = clamp(float(g.get("complexity", 0.1)), 0, 1)
    sensory = clamp(float(g.get("sensory", 0.2)), 0, 1)
    lifespan = clamp(float(g.get("lifespan", 0.3)), 0, 1)
    neural = clamp(0.08 + complexity * 0.54 + sensory * 0.20 + social * 0.10 + lifespan * 0.08, 0.04, 0.98)
    learning = clamp(0.05 + neural * 0.56 + sensory * 0.17 + float(physiology.get("plasticity", 0.3)) * 0.18, 0.03, 0.97)
    memory = clamp(0.06 + neural * 0.57 + lifespan * 0.22 + social * 0.08, 0.03, 0.98)
    planning = clamp((neural - 0.25) * 0.84 + learning * 0.20, 0, 0.92)
    curiosity = clamp(float(g.get("mobility", 0.2)) * 0.38 + sensory * 0.32 + neural * 0.18 - float(g.get("nocturnal", 0)) * 0.04, 0.04, 0.92)
    caution = clamp(float(g.get("defense", 0.2)) * 0.30 + sensory * 0.25 + neural * 0.22 - float(g.get("aggression", 0.1)) * 0.15, 0.04, 0.94)
    cooperation = clamp(social * 0.58 + neural * 0.20 + float(soma.get("reproduction", {}).get("parental_care_score", 0)) * 0.22, 0.02, 0.96)
    communication = list(dict.fromkeys(str(x) for x in behavior.get("communication", ["chemical"])))
    manipulation = clamp(
        min(1.0, float(body.get("appendages", 0)) / 10.0) * 0.42
        + neural * 0.26
        + float(g.get("engineering", 0)) * 0.32,
        0,
        0.96,
    )
    return {
        "schema": NERVE_SCHEMA_VERSION,
        "architecture": {
            "type": _architecture_name(neural),
            "neural_complexity": round(neural, 5),
            "centralization": round(clamp((neural - 0.18) / 0.80, 0, 1), 5),
            "memory_capacity": round(memory, 5),
            "learning_rate": round(learning, 5),
            "planning_horizon": round(planning, 5),
            "cognitive_cost": round(clamp(0.012 + neural ** 1.75 * 0.145, 0.012, 0.18), 5),
        },
        "perception": {
            "modalities": senses,
            "radius": round(clamp(0.12 + sensory * 0.68 + neural * 0.14, 0.08, 0.94), 5),
            "threat_sensitivity": round(caution, 5),
            "resource_sensitivity": round(clamp(0.24 + sensory * 0.36 + neural * 0.22, 0.1, 0.94), 5),
            "social_sensitivity": round(clamp(0.08 + social * 0.60 + neural * 0.18, 0.04, 0.96), 5),
        },
        "temperament": {
            "curiosity": round(curiosity, 5),
            "caution": round(caution, 5),
            "boldness": round(clamp(0.52 + float(g.get("aggression", 0)) * 0.28 + curiosity * 0.20 - caution * 0.36, 0.02, 0.96), 5),
            "sociability": round(social, 5),
        },
        "social": {
            "cooperation": round(cooperation, 5),
            "recognition": round(clamp(neural * 0.45 + social * 0.42, 0.02, 0.94), 5),
            "reciprocity": round(clamp((neural - 0.35) * 0.52 + social * 0.38, 0, 0.90), 5),
            "teaching": round(clamp((neural - 0.62) * 0.72 + social * 0.24, 0, 0.72), 5),
            "communication": communication,
            "signal_complexity": round(clamp(0.08 + sensory * 0.30 + social * 0.34 + neural * 0.24, 0.05, 0.96), 5),
        },
        "manipulation": {
            "score": round(manipulation, 5),
            "tool_capability": False,
            "construction_capability": bool(float(g.get("engineering", 0)) > 0.55 and manipulation > 0.52),
        },
        "repertoire": _initial_repertoire(sp, neural, social),
        "memory": [],
        "known_sites": [],
        "culture": {"traditions": [], "transmission": round(clamp(learning * social * 0.72, 0, 0.88), 5)},
        "selection_pressures": {"cognition": 0.0, "social": 0.0, "learning": 0.0, "manipulation": 0.0},
        "modifiers": {},
        "experience_generations": 0,
        "last_centroid": _centroid(sp),
        "signature": {},
    }


def nerve_signature(nerve: dict[str, Any]) -> dict[str, Any]:
    a = nerve.get("architecture", {})
    s = nerve.get("social", {})
    m = nerve.get("manipulation", {})
    return {
        "architecture": a.get("type"),
        "neural_complexity": round(float(a.get("neural_complexity", 0)), 3),
        "learning": round(float(a.get("learning_rate", 0)), 3),
        "memory": round(float(a.get("memory_capacity", 0)), 3),
        "signal_complexity": round(float(s.get("signal_complexity", 0)), 3),
        "traditions": len(nerve.get("culture", {}).get("traditions", [])),
        "tool_capability": bool(m.get("tool_capability", False)),
    }


def _inherit_nerve(parent: dict[str, Any], child: dict[str, Any], seed: int) -> dict[str, Any]:
    inherited = copy.deepcopy(parent.get("nerve", {}))
    derived = _base_nerve(child, seed)
    if not inherited:
        return derived
    inherited["schema"] = NERVE_SCHEMA_VERSION
    # Architecture remains genetically grounded. Descendants start near the parental
    # cognitive organization while SOMA/genome changes can pull it gradually.
    for section in ("architecture", "perception", "temperament", "social", "manipulation"):
        old = inherited.setdefault(section, {})
        new = derived.get(section, {})
        for key, val in new.items():
            if isinstance(val, (int, float)) and isinstance(old.get(key), (int, float)):
                old[key] = round(float(old[key]) * 0.72 + float(val) * 0.28, 5)
            elif key not in old or key in {"type", "modalities", "communication", "construction_capability"}:
                old[key] = copy.deepcopy(val)
    neural = float(inherited.get("architecture", {}).get("neural_complexity", 0))
    inherited["architecture"]["type"] = _architecture_name(neural)
    inherited["memory"] = []
    inherited["known_sites"] = []
    inherited["experience_generations"] = 0
    inherited["last_centroid"] = _centroid(child)
    inherited["modifiers"] = {}
    inherited["selection_pressures"] = {k: float(v) * 0.35 for k, v in inherited.get("selection_pressures", {}).items()}
    # Culture is not automatically genetic. A descendant lineage retains a weak
    # founder copy only when the parent's cultural transmission is sufficiently high.
    transmission = float(parent.get("nerve", {}).get("culture", {}).get("transmission", 0))
    traditions = copy.deepcopy(parent.get("nerve", {}).get("culture", {}).get("traditions", []))
    inherited["culture"] = {"traditions": [], "transmission": derived["culture"]["transmission"]}
    if transmission > 0.46:
        for t in traditions[-3:]:
            row = copy.deepcopy(t)
            row["strength"] = round(float(row.get("strength", 0.5)) * 0.52, 4)
            row["founder_inherited"] = True
            inherited["culture"]["traditions"].append(row)
    inherited["signature"] = nerve_signature(inherited)
    return inherited


def ensure_nerve_schema(
    sp: dict[str, Any],
    seed: int,
    generation: int,
    species_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parent = (species_by_id or {}).get(str(sp.get("parent_id"))) if sp.get("parent_id") else None
    if not isinstance(sp.get("nerve"), dict) or not sp.get("nerve"):
        sp["nerve"] = _inherit_nerve(parent, sp, seed) if parent and parent.get("nerve") else _base_nerve(sp, seed)
    else:
        nerve = sp["nerve"]
        base = _base_nerve(sp, seed)
        nerve["schema"] = NERVE_SCHEMA_VERSION
        for section in ("architecture", "perception", "temperament", "social", "manipulation", "culture", "selection_pressures"):
            if not isinstance(nerve.get(section), dict):
                nerve[section] = copy.deepcopy(base[section])
            else:
                for k, v in base[section].items():
                    nerve[section].setdefault(k, copy.deepcopy(v))
        nerve.setdefault("repertoire", copy.deepcopy(base["repertoire"]))
        nerve.setdefault("memory", [])
        nerve.setdefault("known_sites", [])
        nerve.setdefault("modifiers", {})
        nerve.setdefault("experience_generations", 0)
        nerve.setdefault("last_centroid", _centroid(sp))
        nerve.setdefault("signature", nerve_signature(nerve))
    sp["nerve"]["memory"] = [m for m in sp["nerve"].get("memory", []) if isinstance(m, dict)][-MAX_MEMORIES:]
    sp["nerve"]["culture"]["traditions"] = [t for t in sp["nerve"]["culture"].get("traditions", []) if isinstance(t, dict)][-MAX_TRADITIONS:]
    sp["nerve"]["repertoire"] = [r for r in sp["nerve"].get("repertoire", []) if isinstance(r, dict)][-MAX_REPERTOIRE:]
    sp["nerve"]["signature"] = nerve_signature(sp["nerve"])
    return sp["nerve"]


def _remember(nerve: dict[str, Any], kind: str, generation: int, position: list[float] | None, strength: float, detail: str) -> None:
    if position is None:
        return
    strength = clamp(strength, 0.02, 1.0)
    rows = nerve.setdefault("memory", [])
    # Reinforce a nearby memory instead of growing state indefinitely.
    for row in reversed(rows):
        if row.get("kind") != kind or not row.get("position"):
            continue
        try:
            if math.dist(row["position"], position) <= 2.5:
                row["strength"] = round(clamp(float(row.get("strength", 0)) * 0.72 + strength * 0.55, 0, 1), 4)
                row["generation"] = generation
                row["detail"] = detail
                return
        except (TypeError, ValueError):
            pass
    rows.append({"kind": kind, "generation": generation, "position": position, "strength": round(strength, 4), "detail": detail})
    nerve["memory"] = rows[-MAX_MEMORIES:]


def _decay_memory(nerve: dict[str, Any]) -> None:
    memory_capacity = float(nerve.get("architecture", {}).get("memory_capacity", 0.2))
    retain = 0.76 + memory_capacity * 0.22
    out = []
    for row in nerve.get("memory", []):
        strength = float(row.get("strength", 0)) * retain
        if strength >= 0.035:
            row = dict(row)
            row["strength"] = round(strength, 4)
            out.append(row)
    nerve["memory"] = out[-MAX_MEMORIES:]


def _memory_strength(nerve: dict[str, Any], kind: str) -> float:
    return clamp(sum(float(x.get("strength", 0)) for x in nerve.get("memory", []) if x.get("kind") == kind) / 2.4, 0, 1)


def _upsert_behavior(nerve: dict[str, Any], name: str, kind: str, strength: float) -> bool:
    rows = nerve.setdefault("repertoire", [])
    for row in rows:
        if row.get("name") == name:
            before = float(row.get("strength", 0))
            row["strength"] = round(clamp(before * 0.74 + strength * 0.36, 0, 1), 4)
            return row["strength"] - before > 0.08
    rows.append({"name": name, "kind": kind, "strength": round(clamp(strength, 0, 1), 4)})
    nerve["repertoire"] = rows[-MAX_REPERTOIRE:]
    return True


def _tradition(nerve: dict[str, Any], name: str, generation: int, position: list[float] | None, strength: float) -> bool:
    rows = nerve.setdefault("culture", {}).setdefault("traditions", [])
    for row in rows:
        if row.get("name") == name:
            row["strength"] = round(clamp(float(row.get("strength", 0.4)) * 0.78 + strength * 0.30, 0, 1), 4)
            row["last_generation"] = generation
            return False
    rows.append({
        "id": f"tr-{stable_int(f'{name}:{generation}:{position}') % 1000000:06d}",
        "name": name,
        "origin_generation": generation,
        "last_generation": generation,
        "position": position,
        "strength": round(clamp(strength, 0.12, 0.92), 4),
    })
    nerve["culture"]["traditions"] = rows[-MAX_TRADITIONS:]
    return True


def _modifiers(sp: dict[str, Any]) -> dict[str, float]:
    nerve = sp.get("nerve", {})
    arch = nerve.get("architecture", {})
    social = nerve.get("social", {})
    temp = nerve.get("temperament", {})
    neural = float(arch.get("neural_complexity", 0.1))
    learning = float(arch.get("learning_rate", 0.1))
    cost = float(arch.get("cognitive_cost", 0.02))
    cooperation = float(social.get("cooperation", 0.1))
    resource_memory = _memory_strength(nerve, "resource")
    threat_memory = _memory_strength(nerve, "threat")
    disease_memory = _memory_strength(nerve, "disease")
    traditions = len(nerve.get("culture", {}).get("traditions", []))
    cultural = clamp(traditions * float(nerve.get("culture", {}).get("transmission", 0)) * 0.08, 0, 0.18)
    return {
        "energy_efficiency": round(clamp(1.0 + learning * 0.07 + resource_memory * 0.12 + cooperation * 0.04 + cultural - cost * 0.42, 0.84, 1.30), 5),
        "predation_mortality": round(clamp(1.0 - threat_memory * 0.18 - learning * 0.06 - cooperation * 0.08, 0.62, 1.05), 5),
        "disease_mortality": round(clamp(1.0 - disease_memory * 0.08 - learning * 0.025, 0.82, 1.04), 5),
        "birth": round(clamp(1.0 - cost * 0.34 + cooperation * 0.025, 0.90, 1.08), 5),
        "mortality": round(clamp(1.0 + cost * 0.18 - neural * 0.025, 0.96, 1.09), 5),
        "capacity": round(clamp(1.0 + resource_memory * 0.05 + cultural * 0.18, 0.96, 1.10), 5),
        "migration": round(clamp(1.0 + float(temp.get("curiosity", 0.2)) * 0.07 + learning * 0.05, 0.96, 1.14), 5),
    }


def _event(generation: int, kind: str, sp: dict[str, Any], text: str, **extra: Any) -> dict[str, Any]:
    row = {"generation": generation, "kind": kind, "subject": sp.get("id"), "text": text}
    row.update(extra)
    return row


def prepare_nerve_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    generation = int(world.get("generation", 0))
    seed = int(world.get("seed", 0))
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    pred_targets = {str(i.get("target")) for i in interactions if i.get("type") == "predation" and float(i.get("strength", 0)) > 0.04}
    events: list[dict[str, Any]] = []
    for sp in species:
        if sp.get("extinct_generation") is not None or float(sp.get("population", 0)) <= 0:
            continue
        nerve = ensure_nerve_schema(sp, seed, generation, by_id)
        _decay_memory(nerve)
        arch = nerve.get("architecture", {})
        learning = float(arch.get("learning_rate", 0.1))
        perception = float(nerve.get("perception", {}).get("radius", 0.1))
        pos = _centroid(sp)
        if str(sp.get("id")) in pred_targets and rng.random() < 0.30 + learning * 0.48:
            _remember(nerve, "threat", generation, pos, 0.35 + perception * 0.45, "predator contact")
            if learning > 0.30:
                _upsert_behavior(nerve, "predator-site-avoidance", "learned", 0.30 + learning * 0.55)
        infection = max([float(v) for v in sp.get("infections", {}).values()] or [0.0])
        if infection > 0.02 and rng.random() < 0.24 + learning * 0.42:
            _remember(nerve, "disease", generation, pos, clamp(infection * 2.3 + learning * 0.3, 0.1, 0.9), "outbreak exposure")
        resources = float(env.get("resources", 0.5))
        # Even simple learners can form weak spatial associations with good or poor
        # feeding grounds. This gives NERVE observable memory before high cognition
        # evolves without granting advanced planning to primitive lineages.
        if rng.random() < 0.10 + learning * 0.24:
            quality = "productive habitat" if resources >= 0.52 else "resource-poor habitat"
            _remember(nerve, "resource", generation, pos, clamp(0.18 + abs(resources - 0.5) * 0.55 + learning * 0.18, 0.1, 0.72), quality)
        nerve["modifiers"] = _modifiers(sp)
        pressure = nerve.setdefault("selection_pressures", {})
        challenges = clamp((_memory_strength(nerve, "threat") + _memory_strength(nerve, "disease") + max(0, 0.55 - resources)) / 2.2, 0, 1)
        pressure["cognition"] = round(clamp(float(pressure.get("cognition", 0)) * 0.82 + challenges * 0.18, 0, 1), 5)
        pressure["learning"] = round(clamp(float(pressure.get("learning", 0)) * 0.82 + challenges * learning * 0.18, 0, 1), 5)
        pressure["social"] = round(clamp(float(pressure.get("social", 0)) * 0.86 + (1 if str(sp.get("id")) in pred_targets else 0) * float(nerve.get("social", {}).get("cooperation", 0)) * 0.08, 0, 1), 5)
        pressure["manipulation"] = round(clamp(float(pressure.get("manipulation", 0)) * 0.92 + float(_genome(sp).get("engineering", 0)) * challenges * 0.03, 0, 1), 5)
        nerve["signature"] = nerve_signature(nerve)
    return events


def finalize_nerve_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    generation = int(world.get("generation", 0))
    seed = int(world.get("seed", 0))
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    events: list[dict[str, Any]] = []
    for sp in species:
        if sp.get("extinct_generation") is not None or float(sp.get("population", 0)) <= 0:
            continue
        nerve = ensure_nerve_schema(sp, seed, generation, by_id)
        arch = nerve.get("architecture", {})
        social = nerve.get("social", {})
        manip = nerve.get("manipulation", {})
        neural = float(arch.get("neural_complexity", 0.1))
        learning = float(arch.get("learning_rate", 0.1))
        memory = float(arch.get("memory_capacity", 0.1))
        transmission = float(nerve.get("culture", {}).get("transmission", 0))
        pos = _centroid(sp)
        prior = nerve.get("last_centroid")
        movement = 0.0
        if prior and pos:
            try:
                movement = math.dist(prior, pos)
            except (TypeError, ValueError):
                movement = 0.0
        nerve["experience_generations"] = int(nerve.get("experience_generations", 0)) + 1

        # Route memory is a true learned behavior: the population has to move, retain
        # spatial information, and have enough learning to stabilize the route.
        if movement > 0.38 and memory > 0.30 and learning > 0.27:
            _remember(nerve, "route", generation, pos, clamp(0.25 + movement * 0.18 + memory * 0.25, 0.1, 0.9), "recent migration route")
            _upsert_behavior(nerve, "route-fidelity", "learned", clamp(0.24 + learning * 0.48 + memory * 0.18, 0, 0.9))
            if transmission > 0.24 and neural > 0.42 and rng.random() < 0.012 + transmission * 0.035:
                if _tradition(nerve, "inherited migration route", generation, pos, 0.30 + transmission * 0.42):
                    events.append(_event(generation, "culture", sp, f"{sp.get('name')} establishes a persistent migration tradition."))

        # Communication repertoire can become a learned social behavior before it is
        # genetically elaborate. More advanced signal systems remain costly and rare.
        signal = float(social.get("signal_complexity", 0.1))
        cooperation = float(social.get("cooperation", 0.1))
        if neural > 0.40 and signal > 0.38 and cooperation > 0.34:
            if _upsert_behavior(nerve, "social-signal-response", "learned", 0.26 + signal * 0.45) and rng.random() < 0.025:
                events.append(_event(generation, "communication", sp, f"{sp.get('name')} develops a more persistent social signaling repertoire."))

        # Stable traditions are cultural state, not a genome flag. They can strengthen,
        # decay, disappear, and cross a speciation event only through founder transfer.
        kept = []
        for tr in nerve.get("culture", {}).get("traditions", []):
            row = dict(tr)
            row["strength"] = round(float(row.get("strength", 0.4)) * (0.90 + transmission * 0.08), 4)
            if row["strength"] >= 0.08:
                kept.append(row)
        nerve["culture"]["traditions"] = kept[-MAX_TRADITIONS:]

        # Tool use requires cognition + SOMA anatomy + engineering pressure. The low
        # per-generation chance intentionally makes this an emergent possibility, not
        # a milestone the simulation is guaranteed to reach.
        g = _genome(sp)
        tool_ready = neural > 0.72 and learning > 0.52 and float(manip.get("score", 0)) > 0.56 and float(g.get("engineering", 0)) > 0.46
        if tool_ready and not manip.get("tool_capability"):
            chance = 0.0005 + max(0, neural - 0.72) * 0.006 + max(0, learning - 0.52) * 0.004 + float(g.get("engineering", 0)) * 0.0012
            if rng.random() < chance:
                manip["tool_capability"] = True
                _upsert_behavior(nerve, "object-assisted-foraging", "learned", 0.58)
                _tradition(nerve, "object-assisted foraging", generation, pos, 0.54)
                events.append(_event(generation, "tool_use", sp, f"{sp.get('name')} begins persistent object-assisted foraging."))

        teach = float(social.get("teaching", 0))
        if teach > 0.22 and transmission > 0.36 and nerve.get("culture", {}).get("traditions") and rng.random() < 0.004 + teach * 0.012:
            _upsert_behavior(nerve, "active-social-learning", "learned", 0.36 + teach * 0.44)
            events.append(_event(generation, "learning", sp, f"{sp.get('name')} shows persistent social transmission of learned behavior."))

        # Occasional ordinary behavioral innovations below tool use. These are much
        # more common than technological behavior and keep NERVE observable early.
        if neural > 0.28 and learning > 0.24 and rng.random() < 0.004 + learning * 0.008:
            candidates = ["refuge-learning", "group-foraging", "localized-vigilance", "seasonal-site-memory", "coordinated-retreat"]
            name = candidates[stable_int(f"{sp.get('id')}:{generation}:behavior") % len(candidates)]
            if _upsert_behavior(nerve, name, "learned", 0.28 + learning * 0.36):
                events.append(_event(generation, "behavior", sp, f"{sp.get('name')} establishes {name.replace('-', ' ')}."))

        nerve["last_centroid"] = pos
        nerve["modifiers"] = _modifiers(sp)
        nerve["signature"] = nerve_signature(nerve)
    return events


def nerve_bias_descendant_genome(
    parent: dict[str, Any],
    child: dict[str, float],
    rng: random.Random,
    magnitude: float = 1.0,
) -> dict[str, float]:
    pressures = parent.get("nerve", {}).get("selection_pressures", {})
    if not pressures:
        return child
    bounds = {
        "complexity": (0.0, 1.0), "sensory": (0.0, 1.0), "sociality": (0.0, 1.0),
        "lifespan": (0.05, 1.0), "engineering": (0.0, 1.0), "mobility": (0.02, 0.75),
    }
    def nudge(key: str, pressure: float, scale: float) -> None:
        if key not in child or key not in bounds or pressure <= 0:
            return
        lo, hi = bounds[key]
        child[key] = round(clamp(float(child[key]) + pressure * scale * magnitude * rng.uniform(0.52, 1.0), lo, hi), 5)
    cognition = clamp(float(pressures.get("cognition", 0)), 0, 1)
    learning = clamp(float(pressures.get("learning", 0)), 0, 1)
    social = clamp(float(pressures.get("social", 0)), 0, 1)
    manipulation = clamp(float(pressures.get("manipulation", 0)), 0, 1)
    # These effects are deliberately weaker than an ordinary mutation. NERVE makes
    # cognition selectable, not inevitable.
    nudge("complexity", cognition, 0.0050)
    nudge("sensory", cognition + learning * 0.5, 0.0045)
    nudge("lifespan", learning, 0.0025)
    nudge("sociality", social, 0.0040)
    nudge("engineering", manipulation, 0.0038)
    nudge("mobility", learning, 0.0018)
    return child


def validate_nerve_state(sp: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nerve = sp.get("nerve")
    if not isinstance(nerve, dict):
        return [f"missing NERVE state {sp.get('id')}"]
    if int(nerve.get("schema", 0)) != NERVE_SCHEMA_VERSION:
        errors.append(f"NERVE schema mismatch {sp.get('id')}")
    arch = nerve.get("architecture", {})
    for key in ("neural_complexity", "memory_capacity", "learning_rate", "planning_horizon"):
        try:
            val = float(arch.get(key, 0))
        except (TypeError, ValueError):
            errors.append(f"invalid NERVE {key} {sp.get('id')}")
            continue
        if not 0 <= val <= 1:
            errors.append(f"NERVE {key} out of bounds {sp.get('id')}")
    if len(nerve.get("memory", [])) > MAX_MEMORIES:
        errors.append(f"NERVE memory overflow {sp.get('id')}")
    if len(nerve.get("culture", {}).get("traditions", [])) > MAX_TRADITIONS:
        errors.append(f"NERVE tradition overflow {sp.get('id')}")
    if len(nerve.get("repertoire", [])) > MAX_REPERTOIRE:
        errors.append(f"NERVE repertoire overflow {sp.get('id')}")
    for row in nerve.get("memory", []):
        if not 0 <= float(row.get("strength", 0)) <= 1:
            errors.append(f"NERVE memory strength invalid {sp.get('id')}")
            break
    return errors


def nerve_catalog(species: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sp in species:
        nerve = sp.get("nerve", {})
        rows.append({
            "id": sp.get("id"), "name": sp.get("name"), "population": round(float(sp.get("population", 0)), 2),
            "born_generation": sp.get("born_generation", 0), "extinct_generation": sp.get("extinct_generation"),
            "architecture": nerve.get("architecture", {}), "perception": nerve.get("perception", {}),
            "temperament": nerve.get("temperament", {}), "social": nerve.get("social", {}),
            "manipulation": nerve.get("manipulation", {}), "repertoire": nerve.get("repertoire", []),
            "memory": nerve.get("memory", []), "culture": nerve.get("culture", {}),
            "signature": nerve.get("signature", nerve_signature(nerve) if nerve else {}),
        })
    return rows


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _bar(x: float, width: float = 170.0) -> float:
    return clamp(float(x), 0, 1) * width


def render_nerve_svg(world: dict[str, Any], species: list[dict[str, Any]], output_path: Path) -> str:
    live = sorted([s for s in species if s.get("extinct_generation") is None], key=lambda s: float(s.get("population", 0)), reverse=True)[:18]
    cols = 2
    card_w, card_h = 660, 330
    rows = max(1, math.ceil(len(live) / cols))
    W, H = 1400, 120 + rows * (card_h + 24)
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         '<rect width="100%" height="100%" fill="#071014"/><style>text{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;fill:#dce8e2}.m{fill:#718982}.a{fill:#9fbcae}.line{stroke:#263b38}.bar{fill:#1a2c29}.fill{fill:#82aa98}</style>',
         f'<text x="40" y="48" font-size="22" letter-spacing="5">PHYLUM / NERVE ETHOGRAM</text><text x="40" y="76" class="m" font-size="11">GEN {int(world.get("generation",0)):06d} · cognition / memory / learning / culture</text>']
    for idx, sp in enumerate(live):
        x = 40 + (idx % cols) * (card_w + 28)
        y = 104 + (idx // cols) * (card_h + 24)
        n = sp.get("nerve", {})
        a = n.get("architecture", {})
        soc = n.get("social", {})
        cult = n.get("culture", {})
        manip = n.get("manipulation", {})
        p.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="9" fill="#0b1619" stroke="#263b38"/>')
        p.append(f'<text x="{x+22}" y="{y+32}" font-size="16">{_esc(sp.get("name"))}</text><text x="{x+card_w-22}" y="{y+32}" class="m" text-anchor="end" font-size="11">{int(float(sp.get("population",0))):,} organisms</text>')
        p.append(f'<text x="{x+22}" y="{y+56}" class="a" font-size="11">{_esc(a.get("type","—"))}</text>')
        metrics = [("NEURAL", a.get("neural_complexity",0)), ("MEMORY",a.get("memory_capacity",0)), ("LEARNING",a.get("learning_rate",0)), ("PLANNING",a.get("planning_horizon",0))]
        for j,(name,val) in enumerate(metrics):
            yy=y+91+j*31; val=float(val or 0)
            p.append(f'<text x="{x+22}" y="{yy}" class="m" font-size="10">{name}</text><rect x="{x+102}" y="{yy-9}" width="170" height="8" rx="4" class="bar"/><rect x="{x+102}" y="{yy-9}" width="{_bar(val):.1f}" height="8" rx="4" class="fill"/><text x="{x+282}" y="{yy}" font-size="10">{val:.2f}</text>')
        rep=[str(r.get("name")) for r in n.get("repertoire",[]) if r.get("name")][-5:]
        p.append(f'<text x="{x+340}" y="{y+88}" class="m" font-size="10">BEHAVIORAL REPERTOIRE</text>')
        for j,name in enumerate(rep): p.append(f'<text x="{x+340}" y="{y+111+j*20}" font-size="10">• {_esc(name.replace("-"," "))}</text>')
        p.append(f'<text x="{x+22}" y="{y+245}" class="m" font-size="10">SOCIAL</text><text x="{x+102}" y="{y+245}" font-size="10">cooperation {float(soc.get("cooperation",0)):.2f} · signals {float(soc.get("signal_complexity",0)):.2f}</text>')
        p.append(f'<text x="{x+22}" y="{y+269}" class="m" font-size="10">MEMORY</text><text x="{x+102}" y="{y+269}" font-size="10">{len(n.get("memory",[]))} retained sites</text>')
        p.append(f'<text x="{x+340}" y="{y+245}" class="m" font-size="10">CULTURE</text><text x="{x+420}" y="{y+245}" font-size="10">{len(cult.get("traditions",[]))} traditions</text>')
        p.append(f'<text x="{x+340}" y="{y+269}" class="m" font-size="10">TOOLS</text><text x="{x+420}" y="{y+269}" font-size="10">{"observed" if manip.get("tool_capability") else "none"}</text>')
        comm=', '.join(str(v) for v in soc.get("communication",[])[:3]) or '—'
        p.append(f'<text x="{x+22}" y="{y+302}" class="m" font-size="10">COMMUNICATION</text><text x="{x+138}" y="{y+302}" font-size="10">{_esc(comm)}</text>')
    p.append('</svg>')
    svg=''.join(p)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return svg


def render_nerve_assets(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], interactions: list[dict[str, Any]], root: Path) -> None:
    render_dir = root / "renders"; docs_dir = root / "docs"
    render_dir.mkdir(parents=True, exist_ok=True); docs_dir.mkdir(parents=True, exist_ok=True)
    plate = render_dir / "nerve.svg"
    render_nerve_svg(world, species, plate)
    shutil.copy2(plate, docs_dir / "nerve.svg")
    data = nerve_catalog(species)
    (docs_dir / "nerve-data.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    data_json = json.dumps(data, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
    gen = int(world.get("generation", 0))
    html_doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PHYLUM / NERVE</title><style>body{{margin:0;background:#071014;color:#dce8e2;font:14px ui-monospace,monospace}}main{{max-width:1500px;margin:auto;padding:20px}}img{{width:100%;height:auto;border:1px solid #263b38}}input{{margin:18px 0;background:#0b1619;border:1px solid #263b38;color:#dce8e2;padding:10px;width:min(440px,100%)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}}.card{{border:1px solid #263b38;background:#0b1619;padding:14px}}.m{{color:#718982}}</style></head><body><main><img src="nerve.svg?gen={gen:06d}" alt="PHYLUM NERVE ethogram"><input id="q" placeholder="filter lineage, behavior, memory, culture"><div class="grid" id="grid"></div></main><script>const DATA={data_json};const g=document.getElementById('grid');function draw(q=''){{q=q.toLowerCase();g.innerHTML=DATA.filter(x=>JSON.stringify(x).toLowerCase().includes(q)).map(x=>{{const a=x.architecture||{{}},s=x.social||{{}},c=x.culture||{{}},m=x.manipulation||{{}};return `<div class="card"><b>${{x.name}}${{x.extinct_generation!==null?' †':''}}</b><div class="m">${{a.type||'—'}} · neural ${{Number(a.neural_complexity||0).toFixed(2)}}</div><p>memory ${{Number(a.memory_capacity||0).toFixed(2)}} · learning ${{Number(a.learning_rate||0).toFixed(2)}} · planning ${{Number(a.planning_horizon||0).toFixed(2)}}</p><p>cooperation ${{Number(s.cooperation||0).toFixed(2)}} · signal complexity ${{Number(s.signal_complexity||0).toFixed(2)}}</p><p>${{(x.repertoire||[]).slice(0,6).map(r=>r.name).join(' · ')||'no retained repertoire'}}</p><p>memory sites: ${{(x.memory||[]).length}} · traditions: ${{(c.traditions||[]).length}} · tools: ${{m.tool_capability?'observed':'none'}}</p></div>`}}).join('')}}draw();document.getElementById('q').addEventListener('input',e=>draw(e.target.value));</script></body></html>'''
    (docs_dir / "nerve.html").write_text(html_doc, encoding="utf-8")
