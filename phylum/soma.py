from __future__ import annotations

import copy
import json
import math
import random
import shutil
from pathlib import Path
from typing import Any

from .utils import clamp, mean, stable_int


SOMA_SCHEMA_VERSION = 1

VALID_REPRODUCTIVE_MODES = {"sexual", "mixed", "clonal"}
VALID_DEVELOPMENT_MODES = {"direct", "metamorphic", "spore-cycle", "alternating"}
VALID_THERMOREGULATION = {"ectothermic", "behavioral", "mesothermic", "endothermic"}


def _role(sp: dict[str, Any]) -> str:
    return str(sp.get("ecology", {}).get("role", "producer"))


def _genome(sp: dict[str, Any]) -> dict[str, float]:
    return {str(k): float(v) for k, v in sp.get("genome", {}).items() if isinstance(v, (int, float))}


def _normalized_budget(parts: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(v)) for v in parts.values()) or 1.0
    return {k: round(max(0.0, float(v)) / total, 4) for k, v in parts.items()}


def _initial_cohorts(population: float, fecundity: float, lifespan: float, role: str) -> dict[str, float]:
    if role == "producer":
        shares = {"propagule": 0.18 + fecundity * 0.08, "juvenile": 0.21, "adult": 0.55, "elder": 0.06}
    else:
        shares = {"propagule": 0.12 + fecundity * 0.09, "juvenile": 0.20, "adult": 0.57, "elder": 0.11 + lifespan * 0.03}
    total = sum(shares.values())
    return {k: round(max(0.0, population) * v / total, 3) for k, v in shares.items()}


def _thermoregulation(g: dict[str, float]) -> str:
    complexity = g.get("complexity", 0.1)
    metabolism_hint = 0.35 * g.get("speed", 0.2) + 0.25 * g.get("body_size", 0.7) / 3 + 0.2 * g.get("sensory", 0.2)
    if complexity > 0.78 and metabolism_hint > 0.52:
        return "endothermic"
    if complexity > 0.56 and metabolism_hint > 0.38:
        return "mesothermic"
    if g.get("mobility", 0.2) > 0.28:
        return "behavioral"
    return "ectothermic"


def _locomotion(g: dict[str, float]) -> list[str]:
    modes: list[str] = []
    mobility = g.get("mobility", 0.2)
    aquatic = g.get("aquatic", 0.0)
    burrow = g.get("burrowing", 0.0)
    speed = g.get("speed", 0.2)
    complexity = g.get("complexity", 0.1)
    body = g.get("body_size", 0.7)
    if mobility < 0.09:
        modes.append("sessile")
    else:
        modes.append("swimming" if aquatic > 0.52 else "crawling")
    if burrow > 0.46:
        modes.append("burrowing")
    if mobility > 0.52 and aquatic < 0.42:
        modes.append("running")
    if speed > 0.68 and complexity > 0.56 and body < 2.6 and aquatic < 0.35:
        modes.append("gliding")
    if speed > 0.82 and complexity > 0.78 and body < 1.8 and aquatic < 0.28:
        modes.append("flight")
    return modes[:3]


def _senses(g: dict[str, float]) -> list[str]:
    sensory = g.get("sensory", 0.2)
    result = ["chemical"]
    if sensory > 0.22:
        result.append("light")
    if sensory > 0.38:
        result.append("vibration")
    if g.get("aquatic", 0.0) > 0.42 and sensory > 0.44:
        result.append("pressure")
    if sensory > 0.63:
        result.append("directional-sound")
    if sensory > 0.84 and g.get("nocturnal", 0.0) > 0.52:
        result.append("echo-ranging")
    return result[:5]


def _feeding_structure(sp: dict[str, Any], g: dict[str, float]) -> str:
    role = _role(sp)
    if role == "predator":
        return "grasping" if g.get("attack", 0) > 0.55 else "piercing"
    if role == "grazer":
        return "rasping"
    if role == "detritivore":
        return "filtering"
    if role == "omnivore":
        return "generalized"
    return "absorptive-frond"


def _support(g: dict[str, float]) -> str:
    if g.get("armor", 0) > 0.64:
        return "external-shell"
    if g.get("body_size", 0.7) > 3.2 and g.get("aquatic", 0) < 0.5:
        return "internal-frame"
    if g.get("aquatic", 0) > 0.55:
        return "hydrostatic"
    return "flexible-support"


def _defenses(g: dict[str, float]) -> list[str]:
    out = []
    if g.get("armor", 0) > 0.28:
        out.append("plating")
    if g.get("speed", 0) > 0.52:
        out.append("escape-speed")
    if g.get("burrowing", 0) > 0.42:
        out.append("burrow-refuge")
    if g.get("defense", 0) > 0.58 and g.get("immune", 0) > 0.50:
        out.append("chemical-defense")
    if g.get("nocturnal", 0) > 0.45:
        out.append("cryptic-coloration")
    return out or ["soft-body"]


def _social_structure(g: dict[str, float]) -> str:
    s = g.get("sociality", 0.2)
    if s > 0.82:
        return "cooperative-colony"
    if s > 0.62:
        return "stable-groups"
    if s > 0.42:
        return "temporary-groups"
    return "solitary"


def _communication(g: dict[str, float], senses: list[str]) -> list[str]:
    out = ["chemical"]
    if "light" in senses and g.get("sexuality", 0) > 0.55:
        out.append("visual-display")
    if "directional-sound" in senses:
        out.append("acoustic")
    if "vibration" in senses and g.get("sociality", 0) > 0.45:
        out.append("substrate-vibration")
    return out[:3]


def _development_mode(sp: dict[str, Any], g: dict[str, float]) -> str:
    role = _role(sp)
    aquatic = g.get("aquatic", 0)
    mobility = g.get("mobility", 0)
    complexity = g.get("complexity", 0)
    if role == "producer" and mobility < 0.16:
        return "spore-cycle"
    if 0.28 < aquatic < 0.75 and mobility > 0.22 and complexity > 0.28:
        return "metamorphic"
    if role == "producer" and complexity > 0.45:
        return "alternating"
    return "direct"


def _reproduction(sp: dict[str, Any], g: dict[str, float], rng: random.Random) -> dict[str, Any]:
    sexuality = g.get("sexuality", 0.6)
    if sexuality > 0.56:
        mode = "sexual"
    elif sexuality > 0.30:
        mode = "mixed"
    else:
        mode = "clonal"

    role = _role(sp)
    aquatic = g.get("aquatic", 0.0)
    if mode == "clonal":
        fertilization = "none"
    elif role == "producer":
        fertilization = "propagule-exchange"
    elif aquatic > 0.52:
        fertilization = "external"
    else:
        fertilization = "internal"

    social = g.get("sociality", 0.2)
    aggression = g.get("aggression", 0.1)
    if fertilization in {"external", "propagule-exchange"}:
        mating_system = "broadcast"
    elif social > 0.68 and aggression < 0.48:
        mating_system = "pair-bonded"
    elif aggression > 0.58:
        mating_system = "competitive"
    elif social > 0.46:
        mating_system = "communal"
    else:
        mating_system = "opportunistic"

    care = clamp(
        0.38 * g.get("complexity", 0.1)
        + 0.30 * social
        + 0.20 * g.get("lifespan", 0.3)
        - 0.24 * g.get("fecundity", 0.4),
        0.0,
        0.92,
    )
    if care > 0.68:
        care_label = "prolonged"
    elif care > 0.42:
        care_label = "guard-and-feed"
    elif care > 0.20:
        care_label = "guarding"
    else:
        care_label = "none"

    fec = g.get("fecundity", 0.4)
    if care > 0.55 or fec < 0.27:
        strategy = "few-invested"
    elif fec > 0.62:
        strategy = "many-small"
    else:
        strategy = "balanced"

    senses = _senses(g)
    courtship = "chemical"
    if "light" in senses and g.get("sensory", 0.2) > 0.45:
        courtship = "visual-display"
    if "directional-sound" in senses and g.get("sociality", 0.2) > 0.42:
        courtship = "acoustic-display"

    return {
        "mode": mode,
        "fertilization": fertilization,
        "mating_system": mating_system,
        "offspring_strategy": strategy,
        "parental_care": care_label,
        "parental_care_score": round(care, 4),
        "seasonality": round(clamp(0.18 + (1 - g.get("tolerance", 0.28)) * 0.42 + sexuality * 0.18, 0.05, 0.88), 4),
        "sexual_dimorphism": round(clamp(sexuality * (0.25 + aggression * 0.45 + g.get("sensory", 0.2) * 0.25), 0, 0.9), 4),
        "courtship": courtship,
    }


def _body_plan(sp: dict[str, Any], g: dict[str, float], rng: random.Random) -> dict[str, Any]:
    complexity = g.get("complexity", 0.1)
    mobility = g.get("mobility", 0.2)
    armor = g.get("armor", 0.1)
    senses = _senses(g)
    inherited_symmetry = sp.get("ecology", {}).get("morphology", {}).get("symmetry")
    symmetry = inherited_symmetry or ("radial" if stable_int(sp.get("id", "x")) % 3 == 0 else "bilateral")
    appendages = int(clamp(round(2 + complexity * 8 + mobility * 4), 0, 16))
    segmentation = int(clamp(round(complexity * 7 + mobility * 2.5), 0, 12))
    covering = "shell" if armor > 0.66 else "plates" if armor > 0.36 else "insulated-hide" if _thermoregulation(g) == "endothermic" else "flexible-skin"
    return {
        "symmetry": symmetry,
        "segmentation": segmentation,
        "support": _support(g),
        "appendages": appendages,
        "locomotion": _locomotion(g),
        "feeding_structure": _feeding_structure(sp, g),
        "covering": covering,
        "defenses": _defenses(g),
        "senses": senses,
        "body_scale": round(g.get("body_size", 0.7), 4),
    }


def _physiology(sp: dict[str, Any], g: dict[str, float]) -> dict[str, Any]:
    thermo = _thermoregulation(g)
    body = g.get("body_size", 0.7)
    speed = g.get("speed", 0.2)
    complexity = g.get("complexity", 0.1)
    aquatic = g.get("aquatic", 0.0)
    metabolism = clamp(0.18 + 0.22 * speed + 0.16 * min(body / 3, 1) + 0.22 * complexity + (0.08 if thermo == "endothermic" else 0), 0.12, 0.96)
    if body < 0.35 and complexity < 0.28:
        respiration = "diffusion"
    elif aquatic > 0.48:
        respiration = "branchial-exchange"
    else:
        respiration = "air-exchange"

    raw_budget = {
        "maintenance": 0.32 + metabolism * 0.20,
        "growth": 0.15 + g.get("fecundity", 0.4) * 0.06,
        "movement": 0.06 + g.get("mobility", 0.2) * 0.18,
        "reproduction": 0.11 + g.get("fecundity", 0.4) * 0.18,
        "immunity": 0.06 + g.get("immune", 0.4) * 0.11,
        "thermoregulation": 0.02 if thermo == "ectothermic" else 0.08 if thermo == "behavioral" else 0.12 if thermo == "mesothermic" else 0.17,
    }
    microbiome = {
        "digestion": round(clamp(0.22 + g.get("detritivory", 0) * 0.34 + g.get("herbivory", 0) * 0.18, 0.05, 0.85), 4),
        "resilience": round(clamp(0.18 + g.get("immune", 0.4) * 0.42 + g.get("tolerance", 0.3) * 0.18, 0.05, 0.9), 4),
        "dependence": round(clamp(g.get("complexity", 0.1) * 0.38 + g.get("herbivory", 0) * 0.20, 0.02, 0.75), 4),
    }
    return {
        "metabolism": round(metabolism, 4),
        "thermoregulation": thermo,
        "respiration": respiration,
        "energy_budget": _normalized_budget(raw_budget),
        "plasticity": round(clamp(0.20 + g.get("tolerance", 0.28) * 0.55 + float(sp.get("genetic_diversity", 0.4)) * 0.24, 0.1, 0.92), 4),
        "microbiome": microbiome,
        "dormancy": "stress-induced" if g.get("tolerance", 0.28) < 0.18 else "seasonal" if g.get("nocturnal", 0.0) > 0.6 else "none",
    }


def _life_cycle(sp: dict[str, Any], g: dict[str, float], population: float) -> dict[str, Any]:
    body = max(0.12, g.get("body_size", 0.7))
    lifespan_gene = g.get("lifespan", 0.35)
    fec = g.get("fecundity", 0.4)
    lifespan = clamp(1.4 + lifespan_gene * 10 + math.log1p(body) * 1.4 - fec * 1.8, 1.2, 18.0)
    maturity = clamp(lifespan * (0.18 + (1 - fec) * 0.18), 0.35, max(0.5, lifespan * 0.68))
    return {
        "development": _development_mode(sp, g),
        "maturity_generations": round(maturity, 3),
        "lifespan_generations": round(lifespan, 3),
        "cohorts": _initial_cohorts(population, fec, lifespan_gene, _role(sp)),
    }


def _behavior(sp: dict[str, Any], g: dict[str, float], body_plan: dict[str, Any]) -> dict[str, Any]:
    senses = body_plan["senses"]
    activity = "nocturnal" if g.get("nocturnal", 0) > 0.58 else "crepuscular" if g.get("nocturnal", 0) > 0.34 else "diurnal"
    territoriality = clamp(0.25 * g.get("aggression", 0) + 0.24 * g.get("defense", 0) + 0.18 * (1 - g.get("sociality", 0.2)), 0, 0.85)
    return {
        "social_structure": _social_structure(g),
        "territoriality": round(territoriality, 4),
        "communication": _communication(g, senses),
        "activity_cycle": activity,
        "migration_tendency": round(clamp(g.get("mobility", 0.2) * 0.72 + g.get("tolerance", 0.3) * 0.14, 0, 0.92), 4),
    }


def _variation(sp: dict[str, Any], g: dict[str, float]) -> dict[str, dict[str, float]]:
    div = clamp(float(sp.get("genetic_diversity", 0.4)), 0.02, 0.95)
    result = {}
    for key in ("body_size", "speed", "fecundity", "defense", "sensory"):
        m = float(g.get(key, 0.0))
        sd = (0.025 + div * 0.10) * (max(0.3, abs(m)) if key == "body_size" else 1.0)
        result[key] = {"mean": round(m, 5), "sd": round(sd, 5)}
    return result


def _base_soma(sp: dict[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(stable_int(f"SOMA:{seed}:{sp.get('id')}:{sp.get('born_generation',0)}"))
    g = _genome(sp)
    population = max(0.0, float(sp.get("population", 0)))
    body = _body_plan(sp, g, rng)
    physiology = _physiology(sp, g)
    result = {
        "schema": SOMA_SCHEMA_VERSION,
        "body_plan": body,
        "life_cycle": _life_cycle(sp, g, population),
        "reproduction": _reproduction(sp, g, rng),
        "physiology": physiology,
        "behavior": _behavior(sp, g, body),
        "variation": _variation(sp, g),
        "selection_pressures": {
            "predation": 0.0,
            "disease": 0.0,
            "competition": 0.0,
            "climate": 0.0,
            "sexual": round(clamp(g.get("sexuality", 0.5) * (0.4 + g.get("sensory", 0.2) * 0.3), 0, 1), 4),
        },
        "innovations": [],
        "symbioses": [],
        "modifiers": {},
    }
    result["signature"] = soma_signature(result)
    return result


def soma_signature(soma: dict[str, Any]) -> dict[str, Any]:
    body = soma.get("body_plan", {})
    life = soma.get("life_cycle", {})
    rep = soma.get("reproduction", {})
    phys = soma.get("physiology", {})
    return {
        "locomotion": tuple(body.get("locomotion", [])),
        "support": body.get("support"),
        "feeding": body.get("feeding_structure"),
        "development": life.get("development"),
        "reproduction": rep.get("mode"),
        "parental_care": rep.get("parental_care"),
        "thermoregulation": phys.get("thermoregulation"),
        "respiration": phys.get("respiration"),
    }


def _inherit_soma(parent: dict[str, Any], child: dict[str, Any], seed: int) -> dict[str, Any]:
    soma = copy.deepcopy(parent.get("soma", {}))
    if not soma:
        return _base_soma(child, seed)
    rng = random.Random(stable_int(f"SOMA-INHERIT:{seed}:{child.get('id')}:{child.get('born_generation',0)}"))
    derived = _base_soma(child, seed)
    soma["schema"] = SOMA_SCHEMA_VERSION

    for section in ("physiology", "reproduction", "behavior"):
        base = soma.setdefault(section, {})
        for k, v in derived.get(section, {}).items():
            if isinstance(v, (int, float)) and isinstance(base.get(k), (int, float)):
                base[k] = round(float(base[k]) * 0.72 + float(v) * 0.28, 4)
            elif k not in base:
                base[k] = copy.deepcopy(v)

    parent_body = soma.setdefault("body_plan", {})
    child_body = derived["body_plan"]
    for key in ("support", "feeding_structure", "covering"):
        if rng.random() < 0.16:
            parent_body[key] = child_body[key]
    for key in ("appendages", "segmentation", "body_scale"):
        pv = float(parent_body.get(key, child_body[key]))
        cv = float(child_body[key])
        nv = pv * 0.72 + cv * 0.28
        parent_body[key] = round(nv, 4) if key == "body_scale" else int(round(nv))
    if rng.random() < 0.12:
        parent_body["locomotion"] = child_body["locomotion"]
    if rng.random() < 0.12:
        parent_body["senses"] = child_body["senses"]
    if rng.random() < 0.10:
        parent_body["defenses"] = child_body["defenses"]

    soma["life_cycle"] = derived["life_cycle"]
    soma["variation"] = derived["variation"]
    soma["selection_pressures"] = copy.deepcopy(parent.get("soma", {}).get("selection_pressures", derived["selection_pressures"]))
    soma["symbioses"] = []
    soma["innovations"] = list(soma.get("innovations", []))[-18:]
    soma["signature"] = soma_signature(soma)
    soma["modifiers"] = {}
    return soma


def ensure_soma_schema(
    sp: dict[str, Any],
    seed: int,
    generation: int,
    species_by_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    species_by_id = species_by_id or {}
    if not isinstance(sp.get("soma"), dict) or not sp.get("soma"):
        parent = species_by_id.get(str(sp.get("parent_id"))) if sp.get("parent_id") else None
        if parent and parent.get("soma"):
            sp["soma"] = _inherit_soma(parent, sp, seed)
        else:
            sp["soma"] = _base_soma(sp, seed)
    else:
        soma = sp["soma"]
        soma["schema"] = SOMA_SCHEMA_VERSION
        base = _base_soma(sp, seed)
        for section in ("body_plan", "life_cycle", "reproduction", "physiology", "behavior", "variation", "selection_pressures"):
            soma.setdefault(section, copy.deepcopy(base[section]))
        soma.setdefault("innovations", [])
        soma.setdefault("symbioses", [])
        soma.setdefault("modifiers", {})
        soma.setdefault("signature", soma_signature(soma))

    cohorts = sp["soma"]["life_cycle"].setdefault("cohorts", {})
    population = max(0.0, float(sp.get("population", 0)))
    if not cohorts or sum(float(v) for v in cohorts.values()) <= 0:
        sp["soma"]["life_cycle"]["cohorts"] = _initial_cohorts(population, _genome(sp).get("fecundity", 0.4), _genome(sp).get("lifespan", 0.3), _role(sp))
    else:
        total = sum(max(0.0, float(v)) for v in cohorts.values()) or 1.0
        sp["soma"]["life_cycle"]["cohorts"] = {k: round(population * max(0.0, float(v)) / total, 3) for k, v in cohorts.items()}



def bias_descendant_genome(
    parent: dict[str, Any],
    child: dict[str, float],
    rng: random.Random,
    magnitude: float = 1.0,
) -> dict[str, float]:
    """Apply weak directional selection accumulated during the parent's lifetime.

    DEEP TIME still owns mutation/recombination. SOMA only nudges a newly formed
    descendant toward traits that were repeatedly favored by organism-level
    pressures. This keeps evolutionary history emergent rather than scripted.
    """
    pressures = parent.get("soma", {}).get("selection_pressures", {})
    if not pressures:
        return child

    bounds = {
        "attack": (0.0, 1.0), "defense": (0.0, 1.0), "speed": (0.0, 1.0),
        "immune": (0.0, 1.0), "sociality": (0.0, 1.0), "aggression": (0.0, 1.0),
        "armor": (0.0, 1.0), "sensory": (0.0, 1.0), "complexity": (0.0, 1.0),
        "tolerance": (0.08, 0.65), "mobility": (0.02, 0.75), "fecundity": (0.04, 0.88),
        "lifespan": (0.05, 1.0), "sexuality": (0.0, 1.0),
    }

    def nudge(locus: str, pressure: float, scale: float, direction: float = 1.0) -> None:
        if locus not in child or locus not in bounds or pressure <= 0:
            return
        lo, hi = bounds[locus]
        # Selection is deliberately much weaker than an ordinary mutation step.
        delta = pressure * scale * magnitude * rng.uniform(0.55, 1.0) * direction
        child[locus] = round(clamp(float(child[locus]) + delta, lo, hi), 5)

    pred = clamp(float(pressures.get("predation", 0)), 0, 1)
    disease = clamp(float(pressures.get("disease", 0)), 0, 1)
    competition = clamp(float(pressures.get("competition", 0)), 0, 1)
    climate = clamp(float(pressures.get("climate", 0)), 0, 1)
    sexual = clamp(float(pressures.get("sexual", 0)), 0, 1)

    # Predator/prey arms races: prey lineages are biased toward escape, detection
    # and protection; predatory parents additionally retain offensive pressure.
    nudge("speed", pred, 0.020)
    nudge("sensory", pred, 0.017)
    nudge("defense", pred, 0.018)
    nudge("armor", pred, 0.012)
    if _role(parent) == "predator":
        nudge("attack", pred, 0.020)
        nudge("aggression", pred, 0.010)

    # Host/pathogen coevolution and environmental instability.
    nudge("immune", disease, 0.024)
    nudge("tolerance", disease, 0.006)
    nudge("tolerance", climate, 0.010)
    nudge("mobility", climate, 0.008)

    # Competition rewards movement, efficiency and flexible life histories.
    nudge("mobility", competition, 0.008)
    nudge("sensory", competition, 0.009)
    nudge("fecundity", competition, 0.006)

    # Sexual selection can favor communication/display complexity even when those
    # traits are not the most efficient route to raw ecological survival.
    nudge("sensory", sexual, 0.008)
    nudge("sociality", sexual, 0.006)
    nudge("complexity", sexual, 0.004)
    if parent.get("soma", {}).get("reproduction", {}).get("mating_system") == "competitive":
        nudge("aggression", sexual, 0.006)

    return child

def _seasonal_multiplier(sp: dict[str, Any], env: dict[str, Any]) -> float:
    rep = sp.get("soma", {}).get("reproduction", {})
    seasonality = float(rep.get("seasonality", 0.2))
    phase = float(env.get("season_phase", 0.0)) % 1.0
    wave = 0.5 + 0.5 * math.cos((phase - 0.18) * math.tau)
    return clamp((1 - seasonality) + seasonality * (0.35 + wave * 1.15), 0.35, 1.45)


def soma_modifiers(sp: dict[str, Any], env: dict[str, Any]) -> dict[str, float]:
    soma = sp.get("soma", {})
    life = soma.get("life_cycle", {})
    rep = soma.get("reproduction", {})
    phys = soma.get("physiology", {})
    beh = soma.get("behavior", {})
    body = soma.get("body_plan", {})
    cohorts = life.get("cohorts", {})
    total = sum(max(0.0, float(v)) for v in cohorts.values()) or max(1.0, float(sp.get("population", 1)))
    adult_share = (float(cohorts.get("adult", 0)) + 0.28 * float(cohorts.get("elder", 0))) / total

    care = float(rep.get("parental_care_score", 0))
    metabolism = float(phys.get("metabolism", 0.4))
    microbiome = phys.get("microbiome", {})
    thermoreg = phys.get("thermoregulation", "ectothermic")
    territoriality = float(beh.get("territoriality", 0))
    defenses = body.get("defenses", [])
    plasticity = float(phys.get("plasticity", 0.3))
    symbioses = soma.get("symbioses", [])
    mutualisms = sum(1 for x in symbioses if x.get("type") == "mutualism")

    birth = (0.58 + adult_share * 0.78) * _seasonal_multiplier(sp, env)
    birth *= 1 - care * 0.17
    mortality = 1.02 - care * 0.10 - float(microbiome.get("resilience", 0.3)) * 0.07 - plasticity * 0.06
    capacity = 1.06 - metabolism * 0.20 + float(microbiome.get("digestion", 0.3)) * 0.10
    mating = 0.78 + adult_share * 0.34 + (0.06 if rep.get("mating_system") in {"communal", "pair-bonded"} else 0)
    mating *= 1.0 + float(rep.get("sexual_dimorphism", 0)) * 0.025
    pred = 1.0 - (0.14 if "plating" in defenses else 0) - (0.10 if "burrow-refuge" in defenses else 0) - (0.07 if beh.get("social_structure") in {"stable-groups", "cooperative-colony"} else 0)
    disease = 1.02 - float(microbiome.get("resilience", 0.3)) * 0.16
    energy = 0.98 + float(microbiome.get("digestion", 0.3)) * 0.11 - metabolism * 0.05
    if mutualisms:
        energy *= 1.0 + min(0.08, mutualisms * 0.025)
        disease *= 1.0 - min(0.06, mutualisms * 0.018)
        capacity *= 1.0 + min(0.06, mutualisms * 0.018)

    dormancy = str(phys.get("dormancy", "none"))
    resources = float(env.get("resources", 0.6))
    phase = float(env.get("season_phase", 0.0)) % 1.0
    if dormancy == "stress-induced" and resources < 0.34:
        birth *= 0.58
        mortality *= 0.84
        energy *= 0.92
    elif dormancy == "seasonal" and (phase < 0.12 or phase > 0.88):
        birth *= 0.72
        mortality *= 0.90

    if thermoreg == "endothermic":
        mortality *= 0.94
        capacity *= 0.92
    elif thermoreg == "mesothermic":
        mortality *= 0.97
        capacity *= 0.96

    mating *= 1.0 + territoriality * 0.04
    energy *= 1.0 - territoriality * 0.025
    return {
        "birth": round(clamp(birth, 0.30, 1.55), 4),
        "mortality": round(clamp(mortality, 0.62, 1.28), 4),
        "capacity": round(clamp(capacity, 0.66, 1.22), 4),
        "mating": round(clamp(mating, 0.55, 1.25), 4),
        "predation_mortality": round(clamp(pred, 0.54, 1.18), 4),
        "disease_mortality": round(clamp(disease, 0.60, 1.16), 4),
        "energy_efficiency": round(clamp(energy, 0.78, 1.17), 4),
    }


def _prune_symbioses(species: list[dict[str, Any]]) -> None:
    """Drop ecological partnerships when living populations no longer share habitat.

    Symbiosis is an ecological relationship, not a permanent species trait. Keeping
    a vanished mutualism in SOMA would otherwise grant benefits forever after two
    ranges separate. A one-cell overlap is enough to keep an existing association;
    new associations still require stronger contact in ``_symbioses`` below.
    """
    live = {
        str(sp.get("id")): sp
        for sp in species
        if sp.get("id") and sp.get("extinct_generation") is None and float(sp.get("population", 0)) > 0
    }
    ranges: dict[str, set[tuple[int, int]]] = {}
    for sid, sp in live.items():
        cells: set[tuple[int, int]] = set()
        for c in sp.get("range", []):
            if isinstance(c, (list, tuple)) and len(c) == 2:
                cells.add((int(c[0]), int(c[1])))
        ranges[sid] = cells

    for sid, sp in live.items():
        rows = sp.get("soma", {}).get("symbioses", [])
        active = []
        for row in rows:
            pid = str(row.get("partner"))
            if pid not in live:
                continue
            if ranges.get(sid, set()) & ranges.get(pid, set()):
                active.append(row)
        sp["soma"]["symbioses"] = active[-12:]


def prepare_soma_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    seed = int(world.get("seed", 0))
    generation = int(world.get("generation", 0))
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    for sp in species:
        ensure_soma_schema(sp, seed, generation, by_id)
    _prune_symbioses(species)
    for sp in species:
        if sp.get("extinct_generation") is None:
            sp["soma"]["modifiers"] = soma_modifiers(sp, env)
    return []


def _rescale_cohorts(cohorts: dict[str, float], population: float) -> dict[str, float]:
    keys = ("propagule", "juvenile", "adult", "elder")
    total = sum(max(0.0, float(cohorts.get(k, 0))) for k in keys)
    if total <= 0:
        return {"propagule": round(population * 0.15, 3), "juvenile": round(population * 0.20, 3), "adult": round(population * 0.58, 3), "elder": round(population * 0.07, 3)}
    result = {k: max(0.0, float(cohorts.get(k, 0))) * population / total for k in keys}
    rounded = {k: round(v, 3) for k, v in result.items()}
    rounded["adult"] = round(max(0.0, rounded["adult"] + population - sum(rounded.values())), 3)
    return rounded


def _advance_cohorts(sp: dict[str, Any]) -> None:
    """Reconcile an aggregate age structure with DEEP TIME's authoritative population.

    SOMA does not simulate individual organisms. Cohorts therefore behave as a
    slowly moving demographic distribution, influenced by recent births/deaths
    and life-history traits, rather than as a literal queue of individual agents.
    """
    soma = sp["soma"]
    life = soma["life_cycle"]
    rep = soma.get("reproduction", {})
    cohorts = {k: max(0.0, float(v)) for k, v in life.get("cohorts", {}).items()}
    for k in ("propagule", "juvenile", "adult", "elder"):
        cohorts.setdefault(k, 0.0)

    population = max(0.0, float(sp.get("population", 0)))
    if population <= 0:
        life["cohorts"] = {k: 0.0 for k in ("propagule", "juvenile", "adult", "elder")}
        return

    births = max(0.0, float(sp.get("last_births", 0)))
    deaths = max(0.0, float(sp.get("last_deaths", 0)))
    pre_death = max(1.0, population + deaths)
    birth_rate = clamp(births / pre_death, 0, 0.55)
    death_rate = clamp(deaths / pre_death, 0, 0.55)
    lifespan = max(1.2, float(life.get("lifespan_generations", 5)))
    maturity = max(0.35, float(life.get("maturity_generations", 1.5)))
    fec = clamp(float(_genome(sp).get("fecundity", 0.4)), 0, 1)
    care = clamp(float(rep.get("parental_care_score", 0)), 0, 1)

    # Target age structure implied by current life history. Long-lived, low-fecundity
    # lineages carry more elders; breeding pulses temporarily increase propagules.
    propagule = clamp(0.055 + birth_rate * 1.45 + fec * 0.055 - care * 0.025, 0.045, 0.30)
    juvenile = clamp(0.13 + (maturity / lifespan) * 0.22 + fec * 0.045 + care * 0.025, 0.11, 0.30)
    elder = clamp(0.028 + (lifespan / 18.0) * 0.13 - fec * 0.025 - death_rate * 0.08, 0.025, 0.18)
    nonadult = propagule + juvenile + elder
    if nonadult > 0.60:
        scale = 0.60 / nonadult
        propagule *= scale; juvenile *= scale; elder *= scale
    target = {"propagule": propagule, "juvenile": juvenile, "elder": elder}
    target["adult"] = max(0.40, 1.0 - propagule - juvenile - elder)
    ttotal = sum(target.values())
    target = {k: v / ttotal for k, v in target.items()}

    old_total = sum(cohorts.values()) or population
    old_share = {k: cohorts[k] / old_total for k in cohorts}
    # Recent mortality reshapes the prior distribution before it is blended toward
    # the life-history target. Propagules and elders are most fragile.
    risk = {"propagule": 1.34, "juvenile": 1.10, "adult": 0.78, "elder": 1.72}
    survived = {k: old_share[k] * max(0.02, 1 - death_rate * risk[k]) for k in old_share}
    stotal = sum(survived.values()) or 1.0
    survived = {k: v / stotal for k, v in survived.items()}

    # Inertia prevents a single strange generation from instantly rewriting the
    # age pyramid, while still allowing multi-generation demographic shifts.
    blend = 0.34
    shares = {k: survived[k] * (1 - blend) + target[k] * blend for k in target}
    life["cohorts"] = _rescale_cohorts({k: shares[k] * population for k in shares}, population)


def _update_selection_pressures(sp: dict[str, Any], interactions: list[dict[str, Any]], env: dict[str, Any]) -> None:
    pressures = sp["soma"].setdefault("selection_pressures", {})
    sid = str(sp.get("id"))
    pred = sum(float(i.get("strength", 0)) for i in interactions if i.get("type") == "predation" and str(i.get("target")) == sid)
    comp = sum(float(i.get("strength", 0)) for i in interactions if i.get("type") == "competition" and (str(i.get("source")) == sid or str(i.get("target")) == sid))
    disease = sum(float(v) for v in sp.get("infections", {}).values())
    climate = 1 - float(sp.get("last_fitness", 0.5))
    for key, value in {
        "predation": clamp(pred * 0.15, 0, 1),
        "competition": clamp(comp * 0.25, 0, 1),
        "disease": clamp(disease, 0, 1),
        "climate": clamp(climate, 0, 1),
    }.items():
        old = float(pressures.get(key, 0))
        pressures[key] = round(clamp(old * 0.86 + value * 0.14, 0, 1), 4)


def _symbioses(species: list[dict[str, Any]], interactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    live = [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]
    ranges = {}
    for sp in live:
        cells = set()
        for c in sp.get("range", []):
            if isinstance(c, (list, tuple)) and len(c) == 2:
                cells.add((int(c[0]), int(c[1])))
        ranges[str(sp.get("id"))] = cells

    added = []
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            overlap = len(ranges[str(a.get("id"))] & ranges[str(b.get("id"))])
            if overlap < 2:
                continue
            ar = _role(a)
            br = _role(b)
            if not ({ar, br} & {"producer", "detritivore", "grazer"}):
                continue
            ag = _genome(a)
            bg = _genome(b)
            complement = abs(ag.get("autotrophy", 0) - bg.get("autotrophy", 0)) + abs(ag.get("detritivory", 0) - bg.get("detritivory", 0))
            social = (ag.get("sociality", 0) + bg.get("sociality", 0)) / 2
            strength = clamp(overlap * 0.012 + complement * 0.08 + social * 0.025, 0, 0.32)
            if strength < 0.055:
                continue
            kind = "mutualism" if complement > 0.35 else "commensalism"
            item = {"type": kind, "source": a["id"], "target": b["id"], "strength": round(strength, 4), "contact_cells": overlap}
            interactions.append(item)
            added.append(item)
            for host, partner in ((a, b), (b, a)):
                rows = host["soma"].setdefault("symbioses", [])
                key = str(partner["id"])
                existing = next((x for x in rows if str(x.get("partner")) == key), None)
                if existing is None:
                    rows.append({"partner": partner["id"], "type": kind, "first_observed": int(host.get("current_generation", 0)), "contact_cells": overlap})
                else:
                    existing["type"] = kind
                    existing["contact_cells"] = overlap
                host["soma"]["symbioses"] = rows[-12:]
    return added


def _innovation_events(world: dict[str, Any], species: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    generation = int(world.get("generation", 0))
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    for sp in species:
        if int(sp.get("born_generation", -1)) != generation:
            continue
        parent = by_id.get(str(sp.get("parent_id")))
        if not parent or not parent.get("soma") or not sp.get("soma"):
            continue
        p_sig = soma_signature(parent["soma"])
        c_sig = soma_signature(sp["soma"])
        changed = [k for k in c_sig if c_sig.get(k) != p_sig.get(k)]
        if not changed:
            continue
        priority = ["locomotion", "thermoregulation", "development", "support", "feeding", "parental_care", "respiration", "reproduction"]
        key = next((k for k in priority if k in changed), changed[0])
        value = c_sig.get(key)
        if isinstance(value, tuple):
            value = ", ".join(value)
        text = f"{sp.get('name','A descendant')} inherits a new {key.replace('_',' ')} pattern: {value}."
        rec = {"generation": generation, "kind": "innovation", "subject": sp.get("id"), "parent": parent.get("id"), "text": text, "innovation": key, "value": value}
        sp["soma"].setdefault("innovations", []).append(rec)
        sp["soma"]["innovations"] = sp["soma"]["innovations"][-24:]
        events.append(rec)
    return events


def finalize_soma_generation(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    seed = int(world.get("seed", 0))
    generation = int(world.get("generation", 0))
    by_id = {str(s.get("id")): s for s in species if s.get("id")}
    for sp in species:
        ensure_soma_schema(sp, seed, generation, by_id)
    for sp in species:
        if sp.get("extinct_generation") is not None or float(sp.get("population", 0)) <= 0:
            continue
        _advance_cohorts(sp)
        _update_selection_pressures(sp, interactions, env)
        sp["soma"]["variation"] = _variation(sp, _genome(sp))
        sp["soma"]["modifiers"] = soma_modifiers(sp, env)
        sp["soma"]["signature"] = soma_signature(sp["soma"])

    sym = _symbioses(species, interactions)
    events = _innovation_events(world, species, seed)
    if sym:
        best = max(sym, key=lambda x: float(x.get("strength", 0)))
        a = by_id.get(str(best.get("source")))
        b = by_id.get(str(best.get("target")))
        if a and b:
            events.append({
                "generation": generation,
                "kind": "symbiosis",
                "subject": a.get("id"),
                "partner": b.get("id"),
                "text": f"{a.get('name')} and {b.get('name')} establish {best.get('type')} in shared habitat.",
            })
    return events


def validate_soma_state(sp: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    soma = sp.get("soma")
    if not isinstance(soma, dict):
        return [f"missing SOMA state {sp.get('id')}"]
    if int(soma.get("schema", 0)) != SOMA_SCHEMA_VERSION:
        errors.append(f"SOMA schema mismatch {sp.get('id')}")
    rep = soma.get("reproduction", {})
    if rep.get("mode") not in VALID_REPRODUCTIVE_MODES:
        errors.append(f"invalid reproductive mode {sp.get('id')}")
    life = soma.get("life_cycle", {})
    if life.get("development") not in VALID_DEVELOPMENT_MODES:
        errors.append(f"invalid development mode {sp.get('id')}")
    thermo = soma.get("physiology", {}).get("thermoregulation")
    if thermo not in VALID_THERMOREGULATION:
        errors.append(f"invalid thermoregulation {sp.get('id')}")
    cohorts = life.get("cohorts", {})
    if sp.get("extinct_generation") is None:
        total = sum(max(0.0, float(v)) for v in cohorts.values())
        pop = max(0.0, float(sp.get("population", 0)))
        if abs(total - pop) > max(0.08, pop * 0.002):
            errors.append(f"cohort/population mismatch {sp.get('id')}")
    budget = soma.get("physiology", {}).get("energy_budget", {})
    if budget and abs(sum(float(v) for v in budget.values()) - 1.0) > 0.015:
        errors.append(f"energy budget mismatch {sp.get('id')}")
    return errors


def soma_catalog(species: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sp in species:
        soma = sp.get("soma", {})
        rows.append({
            "id": sp.get("id"),
            "name": sp.get("name"),
            "population": round(float(sp.get("population", 0)), 2),
            "extinct_generation": sp.get("extinct_generation"),
            "body_plan": soma.get("body_plan", {}),
            "life_cycle": soma.get("life_cycle", {}),
            "reproduction": soma.get("reproduction", {}),
            "physiology": soma.get("physiology", {}),
            "behavior": soma.get("behavior", {}),
            "variation": soma.get("variation", {}),
            "selection_pressures": soma.get("selection_pressures", {}),
            "innovations": soma.get("innovations", []),
            "symbioses": soma.get("symbioses", []),
        })
    return rows


def _color_for(sp: dict[str, Any]) -> str:
    import colorsys
    h = (stable_int(str(sp.get("id", "x"))) % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, 0.60, 0.44)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _organism_glyph(sp: dict[str, Any], cx: float, cy: float, scale: float = 1.0) -> str:
    soma = sp.get("soma", {})
    body = soma.get("body_plan", {})
    physiology = soma.get("physiology", {})
    color = _color_for(sp)
    size = clamp(18 + math.log1p(float(body.get("body_scale", 0.7))) * 12, 18, 42) * scale
    symmetry = body.get("symmetry", "bilateral")
    appendages = int(body.get("appendages", 2))
    segmentation = int(body.get("segmentation", 0))
    covering = body.get("covering", "flexible-skin")
    parts = [f'<g transform="translate({cx:.1f},{cy:.1f})">']
    if symmetry == "radial":
        parts.append(f'<circle cx="0" cy="0" r="{size:.1f}" fill="{color}" fill-opacity=".42" stroke="{color}" stroke-width="2"/>')
    else:
        parts.append(f'<ellipse cx="0" cy="0" rx="{size*1.2:.1f}" ry="{size*.72:.1f}" fill="{color}" fill-opacity=".42" stroke="{color}" stroke-width="2"/>')
    for i in range(max(0, appendages)):
        a = (i / max(1, appendages)) * math.tau
        x1, y1 = math.cos(a) * size * 0.55, math.sin(a) * size * 0.55
        x2, y2 = math.cos(a) * size * 1.5, math.sin(a) * size * 1.5
        parts.append(f'<path d="M{x1:.1f},{y1:.1f} Q{x2*.78:.1f},{y2*.78:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" opacity=".82"/>')
    if segmentation > 0:
        for i in range(1, min(segmentation, 7) + 1):
            xx = -size * 0.8 + i * (size * 1.6 / (min(segmentation, 7) + 1))
            parts.append(f'<line x1="{xx:.1f}" y1="{-size*.48:.1f}" x2="{xx:.1f}" y2="{size*.48:.1f}" stroke="#d9e4df" stroke-opacity=".25" stroke-width=".8"/>')
    if covering in {"plates", "shell"}:
        parts.append(f'<ellipse cx="0" cy="0" rx="{size*.78:.1f}" ry="{size*.48:.1f}" fill="none" stroke="#d9e4df" stroke-opacity=".45" stroke-width="1.2"/>')
    senses = body.get("senses", [])
    if "light" in senses:
        parts.append(f'<circle cx="{size*.72:.1f}" cy="{-size*.18:.1f}" r="{max(1.8,size*.07):.1f}" fill="#e8efe9"/>')
    if physiology.get("thermoregulation") == "endothermic":
        parts.append(f'<circle cx="0" cy="0" r="{size*.22:.1f}" fill="#e8efe9" fill-opacity=".18"/>')
    parts.append("</g>")
    return "".join(parts)


def render_soma_svg(world: dict[str, Any], species: list[dict[str, Any]], output_path: Path) -> str:
    live = [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]
    live.sort(key=lambda s: float(s.get("population", 0)), reverse=True)
    shown = live[:8]
    cols = 2
    card_w = 760
    card_h = 270
    rows = max(1, math.ceil(len(shown) / cols))
    width = 1600
    height = 120 + rows * card_h + 70
    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#071014"/>',
        '<style>text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#dce8e2}.muted{fill:#728880}</style>',
        f'<text x="42" y="48" font-size="21" letter-spacing="5">PHYLUM / SOMA FIELD GUIDE</text>',
        f'<text x="42" y="78" font-size="12" class="muted">GEN {int(world.get("generation",0)):06d} · {len(live)} living lineages · organism-level biology</text>',
    ]
    for idx, sp in enumerate(shown):
        col = idx % cols
        row = idx // cols
        x = 32 + col * (card_w + 16)
        y = 108 + row * card_h
        soma = sp.get("soma", {})
        body = soma.get("body_plan", {})
        life = soma.get("life_cycle", {})
        rep = soma.get("reproduction", {})
        phys = soma.get("physiology", {})
        beh = soma.get("behavior", {})
        cohorts = life.get("cohorts", {})
        pop = max(0.0, float(sp.get("population", 0)))
        color = _color_for(sp)
        p.append(f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h-12}" rx="8" fill="#0b1619" stroke="#263b38"/>')
        p.append(f'<rect x="{x}" y="{y}" width="5" height="{card_h-12}" rx="3" fill="{color}"/>')
        p.append(_organism_glyph(sp, x + 118, y + 105, 1.2))
        p.append(f'<text x="{x+220}" y="{y+34}" font-size="17">{str(sp.get("name","lineage")).upper()}</text>')
        p.append(f'<text x="{x+220}" y="{y+58}" font-size="11" class="muted">{_role(sp)} · {", ".join(body.get("locomotion",[])) or "unknown locomotion"} · {phys.get("thermoregulation","unknown")}</text>')
        p.append(f'<text x="{x+220}" y="{y+88}" font-size="11">body plan</text><text x="{x+330}" y="{y+88}" font-size="11" class="muted">{body.get("symmetry")} · {body.get("support")} · {body.get("appendages",0)} appendages</text>')
        p.append(f'<text x="{x+220}" y="{y+112}" font-size="11">development</text><text x="{x+330}" y="{y+112}" font-size="11" class="muted">{life.get("development")} · maturity {life.get("maturity_generations")} gen · lifespan {life.get("lifespan_generations")} gen</text>')
        p.append(f'<text x="{x+220}" y="{y+136}" font-size="11">reproduction</text><text x="{x+330}" y="{y+136}" font-size="11" class="muted">{rep.get("mode")} · {rep.get("mating_system")} · care {rep.get("parental_care")}</text>')
        p.append(f'<text x="{x+220}" y="{y+160}" font-size="11">senses</text><text x="{x+330}" y="{y+160}" font-size="11" class="muted">{", ".join(body.get("senses",[]))}</text>')
        p.append(f'<text x="{x+220}" y="{y+184}" font-size="11">behavior</text><text x="{x+330}" y="{y+184}" font-size="11" class="muted">{beh.get("social_structure")} · {beh.get("activity_cycle")}</text>')
        bar_x = x + 220
        bar_y = y + 214
        bar_w = 500
        p.append(f'<text x="{bar_x}" y="{bar_y-8}" font-size="10" class="muted">LIFE STAGES</text>')
        cursor = bar_x
        stage_colors = {"propagule":"#6f827a","juvenile":"#8da699","adult":color,"elder":"#4e625a"}
        for stage in ("propagule","juvenile","adult","elder"):
            share = (float(cohorts.get(stage,0)) / pop) if pop > 0 else 0
            w = bar_w * clamp(share,0,1)
            p.append(f'<rect x="{cursor:.1f}" y="{bar_y}" width="{w:.1f}" height="10" fill="{stage_colors[stage]}"/>')
            cursor += w
        p.append(f'<text x="{bar_x}" y="{bar_y+28}" font-size="9" class="muted">propagule / juvenile / adult / elder</text>')
    if len(live) > len(shown):
        p.append(f'<text x="42" y="{height-24}" font-size="11" class="muted">+ {len(live)-len(shown)} additional living lineages available in the Observatory SOMA catalog</text>')
    else:
        p.append(f'<text x="42" y="{height-24}" font-size="11" class="muted">Schematic morphology is generated deterministically from inherited organismal state — not an AI illustration.</text>')
    p.append("</svg>")
    svg = "".join(p)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return svg


def render_individual_organism_svg(sp: dict[str, Any], output_path: Path) -> str:
    width, height = 720, 420
    soma = sp.get("soma", {})
    body = soma.get("body_plan", {})
    life = soma.get("life_cycle", {})
    rep = soma.get("reproduction", {})
    phys = soma.get("physiology", {})
    beh = soma.get("behavior", {})
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#071014"/>',
        '<style>text{font-family:ui-monospace,monospace;fill:#dce8e2}.m{fill:#728880}</style>',
        _organism_glyph(sp, 190, 190, 2.2),
        f'<text x="360" y="58" font-size="18">{str(sp.get("name","lineage")).upper()}</text>',
        f'<text x="360" y="86" font-size="11" class="m">{_role(sp)} · population {int(float(sp.get("population",0))):,}</text>',
        f'<text x="360" y="126" font-size="11">BODY</text><text x="430" y="126" font-size="11" class="m">{body.get("symmetry")} / {body.get("support")}</text>',
        f'<text x="360" y="150" font-size="11">MOVE</text><text x="430" y="150" font-size="11" class="m">{", ".join(body.get("locomotion",[]))}</text>',
        f'<text x="360" y="174" font-size="11">FEED</text><text x="430" y="174" font-size="11" class="m">{body.get("feeding_structure")}</text>',
        f'<text x="360" y="198" font-size="11">SENSE</text><text x="430" y="198" font-size="11" class="m">{", ".join(body.get("senses",[]))}</text>',
        f'<text x="360" y="222" font-size="11">DEV</text><text x="430" y="222" font-size="11" class="m">{life.get("development")}</text>',
        f'<text x="360" y="246" font-size="11">REPRO</text><text x="430" y="246" font-size="11" class="m">{rep.get("mode")} / {rep.get("mating_system")}</text>',
        f'<text x="360" y="270" font-size="11">THERMO</text><text x="430" y="270" font-size="11" class="m">{phys.get("thermoregulation")}</text>',
        f'<text x="360" y="294" font-size="11">SOCIAL</text><text x="430" y="294" font-size="11" class="m">{beh.get("social_structure")}</text>',
        '<text x="32" y="392" font-size="10" class="m">PHYLUM / SOMA · deterministic organismal reconstruction</text>',
        '</svg>',
    ]
    out = "".join(svg)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(out, encoding="utf-8")
    return out


def render_soma_assets(
    world: dict[str, Any],
    species: list[dict[str, Any]],
    env: dict[str, Any],
    interactions: list[dict[str, Any]],
    root: Path,
) -> None:
    render_dir = root / "renders"
    docs_dir = root / "docs"
    guide = render_dir / "soma.svg"
    render_soma_svg(world, species, guide)
    organisms = render_dir / "organisms"
    organisms.mkdir(parents=True, exist_ok=True)
    living = [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]
    for sp in living[:80]:
        render_individual_organism_svg(sp, organisms / f"{sp.get('id')}.svg")
    docs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(guide, docs_dir / "soma.svg")
    (docs_dir / "soma-data.json").write_text(json.dumps(soma_catalog(species), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rows = soma_catalog(species)
    data = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
    html_doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PHYLUM SOMA</title>
<style>:root{{--bg:#071014;--panel:#0b1619;--line:#263b38;--text:#dce8e2;--muted:#748a82}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px ui-monospace,monospace}}header{{padding:22px 28px;border-bottom:1px solid var(--line)}}main{{max-width:1600px;margin:auto;padding:20px}}h1{{font-size:20px;letter-spacing:.25em}}.muted{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}.card{{border:1px solid var(--line);background:var(--panel);padding:15px;border-radius:8px}}input{{width:min(520px,100%);padding:10px;background:#071014;color:var(--text);border:1px solid var(--line);border-radius:6px;margin:0 0 14px}}img{{width:100%;border:1px solid var(--line);border-radius:8px;margin-bottom:16px}}b{{font-weight:600}}</style></head>
<body><header><h1>PHYLUM / SOMA</h1><div class="muted">species evolved. now organisms live. · generation {int(world.get("generation",0)):06d}</div></header>
<main><img src="soma.svg?gen={int(world.get("generation",0)):06d}" alt="PHYLUM SOMA field guide"><input id="q" placeholder="filter living or fossil organisms"><div id="grid" class="grid"></div></main>
<script>const DATA={data};const grid=document.getElementById('grid');function draw(q=''){{q=q.toLowerCase();grid.innerHTML=DATA.filter(x=>JSON.stringify(x).toLowerCase().includes(q)).map(x=>{{const b=x.body_plan||{{}},l=x.life_cycle||{{}},r=x.reproduction||{{}},p=x.physiology||{{}},h=x.behavior||{{}};return `<div class="card"><b>${{x.name}}${{x.extinct_generation!==null?' †':''}}</b><div class="muted">${{Math.round(x.population).toLocaleString()}} organisms</div><p>body: ${{b.symmetry||'—'}} · ${{b.support||'—'}} · ${{(b.locomotion||[]).join(', ')}}</p><p>development: ${{l.development||'—'}} · lifespan ${{l.lifespan_generations||'—'}} gen</p><p>reproduction: ${{r.mode||'—'}} · ${{r.mating_system||'—'}} · care ${{r.parental_care||'—'}}</p><p>physiology: ${{p.thermoregulation||'—'}} · ${{p.respiration||'—'}}</p><p>social: ${{h.social_structure||'—'}} · ${{h.activity_cycle||'—'}}</p></div>`}}).join('')}}draw();document.getElementById('q').addEventListener('input',e=>draw(e.target.value));</script></body></html>'''
    (docs_dir / "soma.html").write_text(html_doc, encoding="utf-8")
