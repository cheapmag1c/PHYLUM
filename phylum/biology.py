from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from typing import Any

from .constants import ADJECTIVES, GRID_COLS, GRID_ROWS, MAX_LIVING_SPECIES, NOUNS, TRAIT_BOUNDS
from .planet import biome_at, cell_world_xy, climate_at, geography_at, neighbors, plate_at, region_name
from .utils import clamp, mean, stable_int, weighted_choice


def normalize_range(sp: dict[str, Any]) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for item in sp.get("range", []):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            x, y = int(item[0]), int(item[1])
            if 0 <= x < GRID_COLS and 0 <= y < GRID_ROWS:
                cells.add((x, y))
    return cells


def store_range(sp: dict[str, Any], cells: set[tuple[int, int]]) -> None:
    sp["range"] = [[x, y] for x, y in sorted(cells, key=lambda c: (c[1], c[0]))]


def territory_target(sp: dict[str, Any]) -> int:
    pop = max(0.0, float(sp.get("population", 0)))
    body = max(0.12, float(sp.get("traits", {}).get("body_size", 1.0)))
    mobility = float(sp.get("traits", {}).get("mobility", 0.2))
    return int(clamp(round(2 + math.sqrt(pop) / (1.9 * body ** 0.18) * (0.84 + mobility)), 2, 130))


def _default_genome(sp: dict[str, Any], rng: random.Random) -> dict[str, float]:
    t = sp.setdefault("traits", {})
    defaults = {
        "temp_pref": float(t.get("temp_pref", 0.5)),
        "moisture_pref": float(t.get("moisture_pref", 0.5)),
        "tolerance": float(t.get("tolerance", 0.28)),
        "mobility": float(t.get("mobility", 0.18)),
        "fecundity": float(t.get("fecundity", 0.38)),
        "body_size": float(t.get("body_size", 0.7)),
        "attack": rng.uniform(0.08, 0.24),
        "defense": rng.uniform(0.12, 0.32),
        "speed": clamp(float(t.get("mobility", 0.18)) * 1.7 + rng.uniform(0, 0.15), 0, 1),
        "immune": rng.uniform(0.25, 0.52),
        "sociality": rng.uniform(0.15, 0.58),
        "aggression": rng.uniform(0.05, 0.28),
        "burrowing": rng.uniform(0.0, 0.18),
        "nocturnal": rng.uniform(0.0, 0.32),
        "armor": rng.uniform(0.05, 0.24),
        "sensory": rng.uniform(0.14, 0.42),
        "complexity": rng.uniform(0.03, 0.13),
        "engineering": rng.uniform(0.0, 0.08),
        "sexuality": rng.uniform(0.52, 0.82),
        "recombination": rng.uniform(0.25, 0.58),
        "lifespan": rng.uniform(0.25, 0.58),
        # The ancestral species remain largely primary producers. Diet can evolve away from this.
        "autotrophy": rng.uniform(0.62, 0.92),
        "herbivory": rng.uniform(0.02, 0.16),
        "carnivory": rng.uniform(0.0, 0.08),
        "detritivory": rng.uniform(0.03, 0.17),
        "aquatic": rng.uniform(0.0, 0.16),
    }
    return {k: round(clamp(v, *TRAIT_BOUNDS[k]), 5) for k, v in defaults.items()}


def sync_traits(sp: dict[str, Any]) -> None:
    g = sp.get("genome", {})
    t = sp.setdefault("traits", {})
    for key in ("temp_pref", "moisture_pref", "tolerance", "mobility", "fecundity", "body_size"):
        if key in g:
            t[key] = round(float(g[key]), 5)


def trophic_role(sp: dict[str, Any]) -> str:
    g = sp.get("genome", {})
    values = {
        "producer": float(g.get("autotrophy", 0)),
        "grazer": float(g.get("herbivory", 0)),
        "predator": float(g.get("carnivory", 0)),
        "detritivore": float(g.get("detritivory", 0)),
    }
    if values["predator"] > 0.32 and values["predator"] > values["producer"] * 0.55 and values["predator"] >= values["grazer"]:
        return "predator"
    if values["grazer"] > 0.32 and values["grazer"] > values["producer"] * 0.52:
        return "grazer"
    if values["detritivore"] > 0.38 and values["detritivore"] > values["producer"] * 0.62:
        return "detritivore"
    if values["producer"] > 0.46:
        return "producer"
    return "omnivore"


def morphology(sp: dict[str, Any]) -> dict[str, Any]:
    g = sp.get("genome", {})
    body = float(g.get("body_size", sp.get("traits", {}).get("body_size", 1)))
    complexity = float(g.get("complexity", 0.1))
    armor = float(g.get("armor", 0.1))
    mobility = float(g.get("mobility", 0.2))
    return {
        "body_scale": round(body, 3),
        "symmetry": "radial" if stable_int(sp.get("id", "x")) % 3 == 0 else "bilateral",
        "appendages": int(clamp(round(2 + complexity * 8 + mobility * 4), 0, 12)),
        "armor": "heavy" if armor > 0.68 else "plated" if armor > 0.38 else "soft",
        "sensory": "advanced" if float(g.get("sensory", 0.2)) > 0.68 else "simple",
        "profile": trophic_role(sp),
    }


def behavior_profile(sp: dict[str, Any]) -> list[str]:
    g = sp.get("genome", {})
    traits = []
    if float(g.get("sociality", 0)) > 0.64: traits.append("social")
    if float(g.get("aggression", 0)) > 0.62: traits.append("territorial")
    if float(g.get("burrowing", 0)) > 0.56: traits.append("burrowing")
    if float(g.get("nocturnal", 0)) > 0.58: traits.append("nocturnal")
    if float(g.get("mobility", 0)) > 0.52: traits.append("migratory")
    if float(g.get("complexity", 0)) > 0.72: traits.append("complex-behavior")
    return traits or ["sessile" if float(g.get("mobility", 0.2)) < 0.12 else "wandering"]


def migrate_species_schema(sp: dict[str, Any], seed: int, generation: int) -> None:
    rng = random.Random(stable_int(f"{seed}:{sp.get('id')}:{sp.get('born_generation',0)}"))
    if "genome" not in sp:
        sp["genome"] = _default_genome(sp, rng)
    else:
        # Backfill newly introduced loci without changing established values.
        base = _default_genome(sp, rng)
        for k, v in base.items():
            sp["genome"].setdefault(k, v)
    sync_traits(sp)
    sp.setdefault("genetic_diversity", round(rng.uniform(0.32, 0.56), 4))
    sp.setdefault("heterozygosity", round(rng.uniform(0.28, 0.52), 4))
    sp.setdefault("sex_mode", "sexual" if sp["genome"]["sexuality"] > 0.48 else "mixed")
    sp.setdefault("inbreeding", 0.0)
    sp.setdefault("infections", {})
    sp.setdefault("peak_population", round(float(sp.get("population", 0)), 2))
    sp.setdefault("peak_range", len(normalize_range(sp)))
    sp.setdefault("offspring_lineages", [])
    sp.setdefault("extinction_cause", None)
    sp.setdefault("last_range", [])
    sp.setdefault("regions_seen", [])
    sp.setdefault("migration_trail", [])
    sp.setdefault("ecology", {})
    sp["ecology"].setdefault("role", trophic_role(sp))
    sp["ecology"].setdefault("behavior", behavior_profile(sp))
    sp["ecology"]["morphology"] = morphology(sp)
    sp.setdefault("origin_generation", int(sp.get("born_generation", generation)))
    sp.setdefault("native_lineage", "PHYLUM/origin")


def cell_suitability(sp: dict[str, Any], cell: tuple[int, int], env: dict[str, Any], plates: dict[str, Any], seed: int) -> float:
    x, y = cell_world_xy(cell, env)
    t, m, resources = climate_at(env, plates, x, y, seed)
    geo = geography_at(env, plates, x, y, seed)
    g = sp.get("genome", sp.get("traits", {}))
    aquatic = float(g.get("aquatic", 0.0))
    if geo["land"] and aquatic > 0.72:
        habitat = 0.22
    elif not geo["land"] and aquatic < 0.35:
        habitat = 0.18
    else:
        habitat = 1.0
    td = abs(t - float(g.get("temp_pref", 0.5)))
    md = abs(m - float(g.get("moisture_pref", 0.5)))
    tol = max(0.08, float(g.get("tolerance", 0.28)))
    climate_fit = max(0.0, 1 - (td + md) / (tol * 2.25))
    burrow = float(g.get("burrowing", 0.0))
    relief_bonus = 0.08 * burrow * geo["relief"]
    return clamp(habitat * (0.69 * climate_fit + 0.31 * min(resources, 1.0) + relief_bonus), 0, 1)


def _connected_components(cells: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    unseen = set(cells)
    comps = []
    while unseen:
        start = unseen.pop()
        comp = {start}
        q = deque([start])
        while q:
            c = q.popleft()
            for n in neighbors(c):
                if n in unseen:
                    unseen.remove(n); comp.add(n); q.append(n)
        comps.append(comp)
    return sorted(comps, key=len, reverse=True)


def _range_centroid(cells: set[tuple[int, int]]) -> tuple[float, float]:
    if not cells: return (GRID_COLS / 2, GRID_ROWS / 2)
    return mean(c[0] for c in cells), mean(c[1] for c in cells)


def _pair_overlap(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> tuple[int, int]:
    overlap = len(a & b)
    border = 0
    if a and b:
        bset = set(b)
        for c in a:
            if any(n in bset for n in neighbors(c)):
                border += 1
    return overlap, border


def build_food_web(species: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float], dict[str, float], dict[str, float]]:
    living = [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]
    ranges = {s["id"]: normalize_range(s) for s in living}
    interactions: list[dict[str, Any]] = []
    predation_loss = defaultdict(float)
    food_gain = defaultdict(float)
    competition = defaultdict(float)
    for i, a in enumerate(living):
        for b in living[i + 1:]:
            overlap, border = _pair_overlap(ranges[a["id"]], ranges[b["id"]])
            contact = overlap + border * 0.35
            if contact <= 0:
                continue
            ga, gb = a["genome"], b["genome"]
            # Resource/niche competition.
            niche_sim = 1 - min(1.0, abs(ga["temp_pref"] - gb["temp_pref"]) + abs(ga["moisture_pref"] - gb["moisture_pref"]))
            diet_sim = 1 - min(1.0, abs(ga["autotrophy"] - gb["autotrophy"]) + abs(ga["herbivory"] - gb["herbivory"]) + abs(ga["carnivory"] - gb["carnivory"])) / 3
            comp = contact * niche_sim * diet_sim * 0.006
            competition[a["id"]] += comp
            competition[b["id"]] += comp
            if comp > 0.025:
                interactions.append({"type": "competition", "source": a["id"], "target": b["id"], "strength": round(comp, 4), "contact_cells": overlap})
            # Directional predation both ways, based on diet and attack/defense/body-size matchup.
            for predator, prey in ((a, b), (b, a)):
                pg, qg = predator["genome"], prey["genome"]
                carn = float(pg.get("carnivory", 0))
                herb = float(pg.get("herbivory", 0))
                prey_auto = float(qg.get("autotrophy", 0))
                edible = carn + herb * prey_auto * 0.45
                if edible < 0.18:
                    continue
                attack = 0.45 * pg.get("attack", 0) + 0.25 * pg.get("speed", 0) + 0.15 * pg.get("sensory", 0)
                defense = 0.4 * qg.get("defense", 0) + 0.28 * qg.get("armor", 0) + 0.18 * qg.get("speed", 0)
                size_ratio = float(pg.get("body_size", 1)) / max(0.1, float(qg.get("body_size", 1)))
                size_match = math.exp(-abs(math.log(max(size_ratio, 0.05))) * 0.45)
                strength = contact * edible * clamp(0.42 + attack - defense * 0.65, 0.05, 1.25) * size_match * 0.012
                if strength <= 0.012:
                    continue
                capacity = min(float(prey["population"]) * 0.08, strength * 5.5)
                predation_loss[prey["id"]] += capacity
                food_gain[predator["id"]] += capacity * 0.35
                interactions.append({"type": "predation", "source": predator["id"], "target": prey["id"], "strength": round(strength, 4), "contact_cells": overlap})
    return interactions, dict(predation_loss), dict(food_gain), dict(competition)


def _mating_factor(sp: dict[str, Any]) -> float:
    pop = max(0.0, float(sp.get("population", 0)))
    g = sp["genome"]
    sexuality = float(g.get("sexuality", 0.6))
    diversity = float(sp.get("genetic_diversity", 0.4))
    inbreeding = float(sp.get("inbreeding", 0.0))
    encounter = 1 - math.exp(-pop / (26 + 40 * float(g.get("body_size", 1))))
    sexual = encounter * (0.68 + 0.32 * diversity) * (1 - 0.55 * inbreeding)
    asexual = 0.75
    return clamp(sexuality * sexual + (1 - sexuality) * asexual, 0.08, 1.0)


def _adjust_genetic_diversity(sp: dict[str, Any], rng: random.Random) -> None:
    pop = max(1.0, float(sp.get("population", 1)))
    div = float(sp.get("genetic_diversity", 0.4))
    recomb = float(sp["genome"].get("recombination", 0.4))
    bottleneck = clamp((90 - pop) / 90, 0, 1)
    div += 0.004 * recomb - 0.012 * bottleneck + rng.gauss(0, 0.0015)
    sp["genetic_diversity"] = round(clamp(div, 0.02, 0.95), 5)
    sp["heterozygosity"] = round(clamp(float(sp.get("heterozygosity", div)) * 0.995 + div * 0.005, 0.01, 0.98), 5)
    sp["inbreeding"] = round(clamp(float(sp.get("inbreeding", 0)) * 0.985 + bottleneck * 0.012 - recomb * 0.002, 0, 0.85), 5)


def _energy_score(sp: dict[str, Any], local_resource: float, food_gain: float, detritus: float) -> float:
    g = sp["genome"]
    producer = float(g.get("autotrophy", 0)) * local_resource
    graze = float(g.get("herbivory", 0)) * min(1.0, food_gain * 0.012 + 0.18)
    hunt = float(g.get("carnivory", 0)) * min(1.0, food_gain * 0.018)
    det = float(g.get("detritivory", 0)) * min(1.0, detritus * 0.002)
    mix = producer + graze + hunt + det
    return clamp(0.24 + mix, 0.08, 1.35)


def _territory_update(sp: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], seed: int, rng: random.Random) -> list[dict[str, Any]]:
    events = []
    cells = normalize_range(sp)
    if not cells:
        return events
    target = territory_target(sp)
    # Shrink poorest cells first.
    while len(cells) > target:
        worst = min(cells, key=lambda c: cell_suitability(sp, c, env, plates, seed) + rng.random() * 0.03)
        cells.remove(worst)
    # Expand into best connected frontier.
    attempts = 0
    while len(cells) < target and attempts < 240:
        attempts += 1
        frontier = {n for c in cells for n in neighbors(c) if n not in cells}
        if not frontier: break
        candidate = max(frontier, key=lambda c: cell_suitability(sp, c, env, plates, seed) + rng.random() * 0.055)
        if cell_suitability(sp, candidate, env, plates, seed) < 0.16 and rng.random() > float(sp["genome"].get("tolerance", 0.25)):
            break
        cells.add(candidate)
    old_centroid = _range_centroid(normalize_range(sp))
    new_centroid = _range_centroid(cells)
    movement = math.dist(old_centroid, new_centroid)
    if movement > 0.48:
        sp.setdefault("migration_trail", []).append({"generation": int(sp.get("current_generation", 0)), "from": [round(old_centroid[0],2),round(old_centroid[1],2)], "to": [round(new_centroid[0],2),round(new_centroid[1],2)]})
        sp["migration_trail"] = sp["migration_trail"][-18:]
    store_range(sp, cells)
    if cells:
        cx, cy = _range_centroid(cells)
        sp["x"] = round((cx + 0.5) * float(env.get("width",160))/GRID_COLS, 3)
        sp["y"] = round((cy + 0.5) * float(env.get("height",100))/GRID_ROWS, 3)
        new_regions = sorted({region_name(c) for c in cells})
        before = set(sp.get("regions_seen", []))
        for reg in new_regions:
            if reg not in before:
                events.append({"kind": "migration", "subject": sp["id"], "text": f"{sp['name']} reaches the {reg}."})
        sp["regions_seen"] = sorted(before | set(new_regions))
    return events


def _mutate_genome(parent: dict[str, Any], rng: random.Random, magnitude: float = 1.0) -> dict[str, float]:
    pg = parent["genome"]
    child = {}
    for key, value in pg.items():
        if key not in TRAIT_BOUNDS:
            child[key] = value
            continue
        lo, hi = TRAIT_BOUNDS[key]
        span = hi - lo
        sigma = (0.025 if key != "body_size" else 0.12) * magnitude
        if key == "body_size":
            v = float(value) * math.exp(rng.gauss(0, sigma))
        else:
            v = float(value) + rng.gauss(0, sigma * min(span, 1.0))
        child[key] = round(clamp(v, lo, hi), 5)
    # Recombination at population level: a few loci move toward alternate allele values.
    recomb = float(pg.get("recombination", 0.4))
    for key in list(child):
        if key in TRAIT_BOUNDS and rng.random() < recomb * 0.18:
            lo, hi = TRAIT_BOUNDS[key]
            child[key] = round(clamp((child[key] + rng.uniform(lo, hi)) * 0.5, lo, hi), 5)
    # Rare metabolic innovations let food-web structure genuinely emerge over deep time.
    if rng.random() < 0.075:
        mode=rng.choice(["herbivory","carnivory","detritivory","autotrophy"])
        child[mode]=round(clamp(float(child.get(mode,0))+rng.uniform(0.16,0.42),0,1),5)
        if mode in {"herbivory","carnivory"}: child["autotrophy"]=round(clamp(float(child.get("autotrophy",0))-rng.uniform(0.08,0.28),0,1),5)
    if rng.random() < 0.025:
        child["aquatic"]=round(clamp(float(child.get("aquatic",0))+rng.uniform(-0.25,0.45),0,1),5)
    return child


def _descendant_name(parent: dict[str, Any], rng: random.Random, used: set[str]) -> str:
    # Preserve a hint of ancestry roughly half the time.
    parent_words = parent.get("name", "").split()
    for _ in range(120):
        if parent_words and rng.random() < 0.55:
            if rng.random() < 0.5:
                name = f"{rng.choice(ADJECTIVES)} {parent_words[-1]}"
            else:
                name = f"{parent_words[0]} {rng.choice(NOUNS)}"
        else:
            name = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
        if name not in used:
            return name
    return f"lineage {rng.randrange(1000,9999)}"


def maybe_speciate(world: dict[str, Any], species: list[dict[str, Any]], sp: dict[str, Any], rng: random.Random) -> dict[str, Any] | None:
    living_count = sum(s.get("extinct_generation") is None for s in species)
    if living_count >= MAX_LIVING_SPECIES or float(sp.get("population",0)) < 160:
        return None
    cells = normalize_range(sp)
    comps = _connected_components(cells)
    isolation = (len(comps) > 1 and len(comps[1]) >= 3)
    div = float(sp.get("genetic_diversity", 0.4))
    niche_pressure = 0.25 + float(sp["genome"].get("mobility",0.2)) * 0.25 + float(sp["genome"].get("recombination",0.4)) * 0.25
    chance = 0.0025 + div * 0.003 + (0.015 if isolation else 0) + niche_pressure * 0.001
    if int(world.get("generation", 0)) <= int(world.get("radiation_boost_until", -1)):
        chance *= 4.0
    if rng.random() >= chance:
        return None
    child_id = f"sp-{int(world.get('next_species_id', 1)):05d}"
    world["next_species_id"] = int(world.get("next_species_id",1)) + 1
    used = {s.get("name") for s in species}
    child_cells = set(comps[1]) if isolation else set(rng.sample(list(cells), max(2, min(len(cells)//3, 8))))
    if not child_cells:
        return None
    frac = clamp(len(child_cells) / max(len(cells),1), 0.12, 0.38)
    child_pop = max(28.0, float(sp["population"]) * frac)
    sp["population"] = round(max(1.0, float(sp["population"]) - child_pop), 2)
    if isolation:
        store_range(sp, cells - child_cells)
    child = {
        "id": child_id,
        "name": _descendant_name(sp, rng, used),
        "parent_id": sp["id"],
        "born_generation": int(world["generation"]),
        "origin_generation": int(world["generation"]),
        "extinct_generation": None,
        "population": round(child_pop,2),
        "range": [[x,y] for x,y in sorted(child_cells)],
        "regions_seen": sorted({region_name(c) for c in child_cells}),
        "genome": _mutate_genome(sp, rng, 1.35 if isolation else 1.0),
        "genetic_diversity": round(clamp(div * rng.uniform(0.62,0.91),0.08,0.9),4),
        "heterozygosity": round(clamp(float(sp.get("heterozygosity",div))*rng.uniform(0.68,0.94),0.05,0.95),4),
        "inbreeding": round(rng.uniform(0.02,0.16) if isolation else rng.uniform(0,0.08),4),
        "sex_mode": sp.get("sex_mode","sexual"),
        "infections": {},
        "peak_population": round(child_pop,2),
        "peak_range": len(child_cells),
        "offspring_lineages": [],
        "extinction_cause": None,
        "last_range": [],
        "migration_trail": [],
        "native_lineage": sp.get("native_lineage", world.get("active_lineage","PHYLUM/origin")),
    }
    sync_traits(child)
    child["ecology"] = {"role": trophic_role(child), "behavior": behavior_profile(child), "morphology": morphology(child)}
    cx, cy = _range_centroid(child_cells)
    child["x"] = round((cx+0.5)*160/GRID_COLS,3); child["y"] = round((cy+0.5)*100/GRID_ROWS,3)
    sp.setdefault("offspring_lineages", []).append(child_id)
    return child


def evolve_ecology(
    world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], plates: dict[str, Any],
    disease_mortality: dict[str, float], rng: random.Random,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    generation = int(world["generation"])
    seed = int(world["seed"])
    events: list[dict[str, Any]] = []
    living = [s for s in species if s.get("extinct_generation") is None and float(s.get("population",0)) > 0]
    for sp in living:
        sp["current_generation"] = generation
    interactions, pred_loss, food_gain, competition = build_food_web(species)
    total_deaths = 0.0
    new_species = []
    for idx, sp in enumerate(list(living)):
        srng = random.Random(rng.getrandbits(64) ^ stable_int(sp["id"]))
        cells = normalize_range(sp)
        if not cells:
            # Re-seed around legacy x/y if needed.
            x = int(clamp(float(sp.get("x",80))/160*GRID_COLS,0,GRID_COLS-1)); y=int(clamp(float(sp.get("y",50))/100*GRID_ROWS,0,GRID_ROWS-1))
            cells={(x,y)}; store_range(sp,cells)
        fits = [cell_suitability(sp,c,env,plates,seed) for c in cells]
        fit = mean(fits, 0.2)
        local_res = mean(climate_at(env, plates, *cell_world_xy(c,env), seed)[2] for c in cells)
        body=max(0.12,float(sp["genome"].get("body_size",1)))
        carrying = max(16.0, len(cells) * (38.0 + 74.0*local_res) / body**0.23)
        mate = _mating_factor(sp)
        energy = _energy_score(sp, local_res, food_gain.get(sp["id"],0), float(world.get("detritus",0)))
        fec=float(sp["genome"].get("fecundity",0.35))
        density=float(sp["population"])/carrying
        births=max(0.0,float(sp["population"])*fec*0.32*mate*fit*energy*(1-max(0,density-0.82)*0.58))
        baseline_death=float(sp["population"])*(0.012 + (1-fit)*0.042 + max(0,density-1)*0.09)
        predator_death=pred_loss.get(sp["id"],0.0)
        comp_death=min(float(sp["population"])*0.08,competition.get(sp["id"],0.0)*3.4)
        disease_death=min(float(sp["population"])*0.35,disease_mortality.get(sp["id"],0.0))
        old=float(sp["population"])
        new=old + births - baseline_death - predator_death - comp_death - disease_death
        # Soft floor only for non-catastrophic normal ecology; tiny populations may still die.
        new=max(0.0,new)
        sp["population"] = round(new,2)
        sp["last_fitness"] = round(fit,4)
        sp["last_births"] = round(births,2)
        sp["last_deaths"] = round(max(0,old+births-new),2)
        sp["last_mating_success"] = round(mate,4)
        sp["ecology"] = {
            "role": trophic_role(sp), "behavior": behavior_profile(sp), "morphology": morphology(sp),
            "energy": round(energy,4), "carrying_capacity": round(carrying,2),
            "predation_pressure": round(predator_death/max(old,1),4),
            "competition_pressure": round(comp_death/max(old,1),4),
        }
        _adjust_genetic_diversity(sp,srng)
        sp["peak_population"]=round(max(float(sp.get("peak_population",0)),new),2)
        _tectonic_transport(sp,env,plates)
        range_events=_territory_update(sp,env,plates,seed,srng)
        for e in range_events:
            e["generation"]=generation; events.append(e)
        sp["peak_range"]=max(int(sp.get("peak_range",0)),len(normalize_range(sp)))
        total_deaths += max(0, old + births - new)
        # Extinction threshold is intentionally low enough for real collapses but avoids rounding noise.
        if new < 1.5:
            sp["last_range"] = sp.get("range", [])
            sp["extinct_generation"] = generation
            causes = [("disease",disease_death),("predation",predator_death),("competition",comp_death),("starvation",baseline_death*(1-energy)),("climate",baseline_death*(1-fit))]
            cause=max(causes,key=lambda p:p[1])[0]
            sp["extinction_cause"] = cause
            sp["population"] = 0.0
            events.append({"generation":generation,"kind":"extinction","subject":sp["id"],"text":f"{sp['name']} becomes extinct after {cause} pressure.","cause":cause})
            continue
        child=maybe_speciate(world,species+new_species,sp,srng)
        if child:
            new_species.append(child)
            events.append({"generation":generation,"kind":"speciation","subject":child["id"],"parent":sp["id"],"text":f"{child['name']} diverges from {sp['name']}."})
    species.extend(new_species)
    hybrid,hybrid_event=maybe_hybridize(world,species,random.Random(rng.getrandbits(64)))
    if hybrid:
        species.append(hybrid)
        if hybrid_event: events.append(hybrid_event)
    world["detritus"] = round(clamp(float(world.get("detritus",0))*0.82 + total_deaths*0.14,0,50000),2)
    return interactions, events




def maybe_hybridize(world: dict[str, Any], species: list[dict[str, Any]], rng: random.Random) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    living=[s for s in species if s.get("extinct_generation") is None and float(s.get("population",0))>90 and float(s.get("genome",{}).get("sexuality",0))>0.52]
    if len(living)<2 or sum(s.get("extinct_generation") is None for s in species)>=MAX_LIVING_SPECIES:
        return None,None
    pairs=[]
    for i,a in enumerate(living):
        ra=normalize_range(a)
        for b in living[i+1:]:
            rb=normalize_range(b); overlap=len(ra & rb)
            if overlap<2: continue
            keys=[k for k in a["genome"] if k in b["genome"] and k in TRAIT_BOUNDS and k!="body_size"]
            dist=mean(abs(float(a["genome"][k])-float(b["genome"][k])) for k in keys)
            if dist>0.17: continue
            chance=0.00045 + overlap*0.00012 + (0.17-dist)*0.0015
            pairs.append((a,b,chance))
    for a,b,chance in pairs:
        if rng.random()>=chance: continue
        used={s.get("name") for s in species}
        child_id=f"sp-{int(world.get('next_species_id',1)):05d}"; world["next_species_id"]=int(world.get("next_species_id",1))+1
        g={}
        for k in set(a["genome"])|set(b["genome"]):
            if k in TRAIT_BOUNDS:
                lo,hi=TRAIT_BOUNDS[k]; av=float(a["genome"].get(k,(lo+hi)/2)); bv=float(b["genome"].get(k,(lo+hi)/2)); g[k]=round(clamp((av+bv)/2+rng.gauss(0,(hi-lo)*0.008),lo,hi),5)
        shared=normalize_range(a)&normalize_range(b); child_cells=set(shared) if shared else set(list(normalize_range(a)|normalize_range(b))[:4])
        founder=max(24.0,min(float(a["population"]),float(b["population"]))*0.045)
        a["population"]=round(max(2,float(a["population"])-founder*.5),2); b["population"]=round(max(2,float(b["population"])-founder*.5),2)
        child={"id":child_id,"name":_descendant_name(a,rng,used),"parent_id":a["id"],"secondary_parent_id":b["id"],"born_generation":int(world["generation"]),"origin_generation":int(world["generation"]),"extinct_generation":None,"population":round(founder,2),"range":[[x,y] for x,y in sorted(child_cells)],"regions_seen":sorted({region_name(c) for c in child_cells}),"genome":g,"genetic_diversity":round(clamp((float(a.get("genetic_diversity",.4))+float(b.get("genetic_diversity",.4)))/2+0.08,0.05,0.95),4),"heterozygosity":round(clamp((float(a.get("heterozygosity",.4))+float(b.get("heterozygosity",.4)))/2+0.1,0.05,0.98),4),"inbreeding":0.0,"sex_mode":"sexual","infections":{},"peak_population":round(founder,2),"peak_range":len(child_cells),"offspring_lineages":[],"extinction_cause":None,"last_range":[],"migration_trail":[],"native_lineage":a.get("native_lineage",world.get("active_lineage","PHYLUM/origin")),"hybrid_origin":True}
        sync_traits(child); child["ecology"]={"role":trophic_role(child),"behavior":behavior_profile(child),"morphology":morphology(child)}
        a.setdefault("offspring_lineages",[]).append(child_id); b.setdefault("offspring_lineages",[]).append(child_id)
        ev={"generation":int(world["generation"]),"kind":"speciation","subject":child_id,"parent":a["id"],"secondary_parent":b["id"],"text":f"{child['name']} forms through hybridization between {a['name']} and {b['name']}."}
        return child,ev
    return None,None

def apply_ecosystem_engineering(species: list[dict[str, Any]], env: dict[str, Any]) -> None:
    """Persist small local resource/moisture changes created by ecosystem engineers."""
    mods: dict[str, dict[str, float]] = {}
    # Decay prior modifications.
    for item in env.get("biotic_modifiers", []):
        strength = float(item.get("strength", 0.0)) * 0.975
        if strength > 0.01:
            key=f"{int(item.get('x',0))},{int(item.get('y',0))}"
            mods[key]={"x":int(item.get("x",0)),"y":int(item.get("y",0)),"strength":strength,"moisture":float(item.get("moisture",0.0))*0.975}
    for sp in species:
        if sp.get("extinct_generation") is not None: continue
        engineering=float(sp.get("genome",{}).get("engineering",0.0))
        if engineering < 0.28: continue
        cells=normalize_range(sp)
        if not cells: continue
        contribution=min(0.08, engineering * math.log1p(float(sp.get("population",0))) * 0.0025)
        for x,y in list(cells)[:80]:
            key=f"{x},{y}"; cur=mods.get(key,{"x":x,"y":y,"strength":0.0,"moisture":0.0})
            cur["strength"]=clamp(float(cur.get("strength",0))+contribution,0,0.22)
            cur["moisture"]=clamp(float(cur.get("moisture",0))+contribution*0.35,0,0.08)
            mods[key]=cur
    env["biotic_modifiers"]=list(mods.values())[:1200]


def _tectonic_transport(sp: dict[str, Any], env: dict[str, Any], plates: dict[str, Any]) -> None:
    cells=normalize_range(sp)
    if not cells: return
    cx,cy=_range_centroid(cells)
    wx=(cx+0.5)*float(env.get("width",160))/GRID_COLS; wy=(cy+0.5)*float(env.get("height",100))/GRID_ROWS
    p=plate_at(plates,wx,wy,env)
    res=sp.setdefault("plate_drift_residual",[0.0,0.0])
    cellw=float(env.get("width",160))/GRID_COLS; cellh=float(env.get("height",100))/GRID_ROWS
    scale=float(plates.get("drift_scale",0.22))
    res[0]=float(res[0])+float(p.get("vx",0))*scale/cellw
    res[1]=float(res[1])+float(p.get("vy",0))*scale/cellh
    sx=1 if res[0]>=1 else -1 if res[0]<=-1 else 0
    sy=1 if res[1]>=1 else -1 if res[1]<=-1 else 0
    if sx or sy:
        moved={(int(clamp(x+sx,0,GRID_COLS-1)),int(clamp(y+sy,0,GRID_ROWS-1))) for x,y in cells}
        store_range(sp,moved)
        res[0]-=sx; res[1]-=sy
    sp["plate_id"]=p.get("id")

def apply_mass_extinction(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], plates: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    """Rare emergent catastrophe. The trigger is probabilistic/environmental, never tied to a generation number."""
    living=[s for s in species if s.get("extinct_generation") is None and s.get("population",0)>0]
    if len(living) < 2:
        return []
    climate_extreme = abs(float(env.get("temperature",0.55))-0.55) + abs(float(env.get("moisture",0.53))-0.53)
    disease_load = mean(sum(float(v) for v in s.get("infections",{}).values()) for s in living)
    trigger = 0.0007 + climate_extreme*0.0018 + min(0.0025,disease_load*0.0008)
    if rng.random() >= trigger:
        return []
    kind=weighted_choice(rng,[("impact",0.18),("flood-basalt volcanism",0.22),("runaway climate shift",0.22),("ocean anoxia",0.18),("pandemic cascade",0.20)])
    severity=rng.uniform(0.43,0.86)
    before=sum(float(s["population"]) for s in living)
    extinct=0
    for sp in living:
        g=sp["genome"]
        resilience=0.28*float(g.get("tolerance",0.3))+0.24*float(g.get("immune",0.4))+0.16*float(g.get("mobility",0.2))+0.14*float(g.get("burrowing",0.1))+0.1*float(sp.get("genetic_diversity",0.4))
        mortality=clamp(severity*(0.62+rng.uniform(-0.18,0.25))*(1-resilience*0.48),0.18,0.96)
        sp["population"]=round(float(sp["population"])*(1-mortality),2)
        if sp["population"] < 1.5:
            sp["last_range"]=sp.get("range",[]); sp["extinct_generation"]=int(world["generation"]); sp["extinction_cause"]="mass extinction"; sp["population"]=0.0; extinct+=1
    after=sum(float(s["population"]) for s in species if s.get("extinct_generation") is None)
    loss=1-after/max(before,1)
    # Leave a large physical scar.
    env.setdefault("scars",[]).append({"id":f"mass-{world['generation']:06d}","kind":"impact" if kind=="impact" else "volcanic" if "volcan" in kind else "cooling","generation":int(world["generation"]),"x":round(rng.uniform(0,float(env.get("width",160))),3),"y":round(rng.uniform(0,float(env.get("height",100))),3),"radius":round(rng.uniform(28,64),3),"strength":round(severity,4),"severity":round(severity,4)})
    world["last_mass_extinction"]={"generation":int(world["generation"]),"kind":kind,"severity":round(severity,4),"population_loss":round(loss,4),"lineages_lost":extinct}
    world["radiation_boost_until"] = int(world["generation"]) + rng.randint(12,32)
    return [{"generation":int(world["generation"]),"kind":"mass_extinction","subject":"world","text":f"A {kind} causes a mass extinction: {loss*100:.0f}% of organisms are lost and {extinct} lineages vanish.","severity":severity,"population_loss":loss,"lineages_lost":extinct}]
