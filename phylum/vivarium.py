from __future__ import annotations

import copy
import json
import math
import random
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any

from .constants import GRID_COLS, GRID_ROWS, TRAIT_BOUNDS, ADJECTIVES, NOUNS
from .planet import cell_world_xy, climate_at, geography_at, neighbors, region_name
from .storage import ROOT, atomic_json, load_json
from .utils import clamp, stable_int, mean

VIVARIUM_SCHEMA_VERSION = 1
MAX_AGENTS_PER_SPECIES = 96
MAX_TOTAL_AGENTS = 1400
MAX_COHORTS_PER_SPECIES = 32
MAX_AGENT_MEMORY = 12
MAX_AGENT_SOCIAL = 10
DEFAULT_CHECKPOINT_DAYS = 14
YEAR_DAYS = 360

VIVARIUM_PATH = ROOT / "world" / "vivarium.json"
ORGANISMS_PATH = ROOT / "world" / "organisms.json"
COHORTS_PATH = ROOT / "world" / "cohorts.json"
ECOSYSTEM_PATH = ROOT / "world" / "ecosystem.json"
BIRTHS_PATH = ROOT / "fossils" / "births.ndjson"
DEATHS_PATH = ROOT / "fossils" / "deaths.ndjson"

GENE_LOCI = (
    "temp_pref", "moisture_pref", "tolerance", "mobility", "fecundity",
    "body_size", "attack", "defense", "speed", "immune", "sociality",
    "aggression", "sensory", "complexity", "engineering", "lifespan",
    "autotrophy", "herbivory", "carnivory", "detritivory", "aquatic",
    "sexuality", "recombination",
)


def _event(world: dict[str, Any], kind: str, subject: str, text: str, **extra: Any) -> dict[str, Any]:
    row = {
        "generation": int(world.get("generation", 0)),
        "sim_day": round(float(world.get("vivarium", {}).get("sim_day", 0.0)), 3),
        "kind": kind,
        "subject": subject,
        "text": text,
    }
    row.update(extra)
    return row


def _cell_key(cell: tuple[int, int] | list[int]) -> str:
    return f"{int(cell[0])},{int(cell[1])}"


def _parse_cell(value: str | tuple[int, int] | list[int]) -> tuple[int, int]:
    if isinstance(value, str):
        a, b = value.split(",", 1)
        return int(a), int(b)
    return int(value[0]), int(value[1])


def _living(species: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in species if s.get("extinct_generation") is None and float(s.get("population", 0)) > 0]


def _range_cells(sp: dict[str, Any]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for row in sp.get("range", []):
        if isinstance(row, (list, tuple)) and len(row) == 2:
            c = (int(row[0]), int(row[1]))
            if 0 <= c[0] < GRID_COLS and 0 <= c[1] < GRID_ROWS:
                out.append(c)
    if not out:
        x = int(clamp(float(sp.get("x", 80.0)) / 160.0 * GRID_COLS, 0, GRID_COLS - 1))
        y = int(clamp(float(sp.get("y", 50.0)) / 100.0 * GRID_ROWS, 0, GRID_ROWS - 1))
        out = [(x, y)]
    return sorted(set(out))


def _base_gene(sp: dict[str, Any], locus: str) -> float:
    lo, hi = TRAIT_BOUNDS.get(locus, (0.0, 1.0))
    return clamp(float(sp.get("genome", {}).get(locus, sp.get("traits", {}).get(locus, (lo + hi) / 2))), lo, hi)


def _mutated_genes(sp: dict[str, Any], rng: random.Random, scale: float = 0.014) -> dict[str, float]:
    diversity = clamp(float(sp.get("genetic_diversity", 0.4)), 0.02, 0.95)
    genes: dict[str, float] = {}
    for locus in GENE_LOCI:
        lo, hi = TRAIT_BOUNDS.get(locus, (0.0, 1.0))
        width = hi - lo
        base = _base_gene(sp, locus)
        genes[locus] = round(clamp(base + rng.gauss(0.0, width * scale * (0.4 + diversity)), lo, hi), 6)
    return genes


def _phenotype(genes: dict[str, float], cell_state: dict[str, Any]) -> dict[str, float]:
    # Phenotype is not a second genome. Development and current condition alter
    # expression, while inherited gene values remain unchanged.
    nutrition = clamp(float(cell_state.get("producer_biomass", 0.5)) / max(0.2, float(cell_state.get("capacity", 1.0))), 0, 1)
    temp_stress = abs(float(cell_state.get("temperature", 0.5)) - float(genes.get("temp_pref", 0.5)))
    developmental = clamp(0.88 + nutrition * 0.16 - temp_stress * 0.10, 0.72, 1.08)
    return {
        "body_size": round(max(0.02, float(genes.get("body_size", 1.0)) * developmental), 5),
        "speed": round(clamp(float(genes.get("speed", 0.2)) * (0.86 + nutrition * 0.18), 0, 1), 5),
        "immune": round(clamp(float(genes.get("immune", 0.4)) * (0.82 + nutrition * 0.20), 0, 1), 5),
        "sensory": round(clamp(float(genes.get("sensory", 0.2)) * (0.90 + nutrition * 0.12), 0, 1), 5),
    }


def _lifespan_days(genes: dict[str, float], soma: dict[str, Any] | None = None) -> float:
    # Existing SOMA life history remains informative, but VIVARIUM converts it to
    # a continuous day-scale lifespan for individual organisms.
    score = clamp(float(genes.get("lifespan", 0.4)), 0.02, 1.0)
    soma_life = float((soma or {}).get("life_cycle", {}).get("lifespan_generations", 0.0) or 0.0)
    if soma_life > 0:
        return clamp(soma_life * 120.0, 90.0, 7200.0)
    return 120.0 + score * 3300.0


def _maturity_days(genes: dict[str, float], soma: dict[str, Any] | None = None) -> float:
    soma_maturity = float((soma or {}).get("life_cycle", {}).get("maturity_generations", 0.0) or 0.0)
    if soma_maturity > 0:
        return clamp(soma_maturity * 120.0, 25.0, 2200.0)
    return _lifespan_days(genes, soma) * clamp(0.16 + (1 - float(genes.get("fecundity", 0.4))) * 0.16, 0.12, 0.42)


def _stage(age_days: float, genes: dict[str, float], soma: dict[str, Any] | None = None) -> str:
    life = _lifespan_days(genes, soma)
    mature = _maturity_days(genes, soma)
    if age_days < max(5.0, mature * 0.28):
        return "propagule"
    if age_days < mature:
        return "juvenile"
    if age_days < life * 0.80:
        return "adult"
    return "elder"


def _agent_seed(world_seed: int, sid: str, serial: int) -> random.Random:
    return random.Random(stable_int(f"vivarium:founder:{world_seed}:{sid}:{serial}"))


def _next_agent_id(state: dict[str, Any]) -> str:
    n = int(state.get("next_organism_id", 1))
    state["next_organism_id"] = n + 1
    return f"o-{n:09d}"


def _next_cohort_id(state: dict[str, Any]) -> str:
    n = int(state.get("next_cohort_id", 1))
    state["next_cohort_id"] = n + 1
    return f"c-{n:08d}"


def _ecosystem_cell(env: dict[str, Any], plates: dict[str, Any], seed: int, cell: tuple[int, int]) -> dict[str, Any]:
    x, y = cell_world_xy(cell, env)
    t, m, r = climate_at(env, plates, x, y, seed)
    geo = geography_at(env, plates, x, y, seed)
    productivity = clamp(r * (0.48 + m * 0.38) * (0.72 + (1 - abs(t - 0.56)) * 0.32), 0.03, 1.2)
    if not geo.get("land", True):
        productivity *= 0.72 + m * 0.18
    capacity = 18.0 + productivity * 120.0
    return {
        "temperature": round(t, 5),
        "moisture": round(m, 5),
        "productivity": round(productivity, 5),
        "capacity": round(capacity, 4),
        "producer_biomass": round(capacity * (0.38 + productivity * 0.25), 4),
        "detritus": round(capacity * 0.035, 4),
        "nutrients": round(clamp(0.32 + r * 0.52, 0.05, 1.0), 5),
        "water": round(m, 5),
        "land": bool(geo.get("land", True)),
        "elevation": round(float(geo.get("elevation", 0.0)), 5),
    }


def _initial_ecosystem(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any]) -> dict[str, Any]:
    seed = int(world.get("seed", 0))
    cells = {}
    for y in range(GRID_ROWS):
        for x in range(GRID_COLS):
            cells[_cell_key((x, y))] = _ecosystem_cell(env, plates, seed, (x, y))
    return {
        "schema": VIVARIUM_SCHEMA_VERSION,
        "cells": cells,
        "weather": {"temperature_anomaly": 0.0, "rain_anomaly": 0.0, "storm": 0.0},
        "last_recalibrated_checkpoint": int(world.get("generation", 0)),
    }


def _founder_agent(world: dict[str, Any], state: dict[str, Any], sp: dict[str, Any], serial: int, cell: tuple[int, int], eco: dict[str, Any]) -> dict[str, Any]:
    rng = _agent_seed(int(world.get("seed", 0)), str(sp.get("id")), serial)
    genes = _mutated_genes(sp, rng)
    life = _lifespan_days(genes, sp.get("soma"))
    age = rng.uniform(life * 0.12, life * 0.78)
    existing_practices = [str(p.get("name")) for p in sp.get("techne", {}).get("practices", []) if p.get("name")]
    culture = [name for name in existing_practices if rng.random() < 0.35][:6]
    return {
        "id": _next_agent_id(state),
        "species_id": str(sp.get("id")),
        "origin": "VIVARIUM migration founder",
        "born_day": round(float(state.get("sim_day", 0.0)) - age, 3),
        "age_days": round(age, 3),
        "stage": _stage(age, genes, sp.get("soma")),
        "sex": "A" if rng.random() < 0.5 else "B",
        "cell": [cell[0], cell[1]],
        "energy": round(rng.uniform(0.48, 0.88), 5),
        "health": round(rng.uniform(0.72, 1.0), 5),
        "genes": genes,
        "phenotype": _phenotype(genes, eco["cells"][_cell_key(cell)]),
        "parent_ids": [],
        "memory": [],
        "social": {},
        "culture": culture,
        "infections": {},
        "alive": True,
        "cause_of_death": None,
    }


def _founder_cohort(world: dict[str, Any], state: dict[str, Any], sp: dict[str, Any], cell: tuple[int, int], count: float, serial: int) -> dict[str, Any]:
    rng = random.Random(stable_int(f"vivarium:cohort:{world.get('seed')}:{sp.get('id')}:{serial}:{cell}"))
    genes = _mutated_genes(sp, rng, scale=0.008)
    prevalence = {str(k): round(float(v), 5) for k, v in sp.get("infections", {}).items() if float(v) > 0}
    return {
        "id": _next_cohort_id(state),
        "species_id": str(sp.get("id")),
        "cell": [cell[0], cell[1]],
        "count": round(max(0.0, count), 5),
        "mean_age_days": round(_lifespan_days(genes, sp.get("soma")) * rng.uniform(0.24, 0.55), 3),
        "energy": round(rng.uniform(0.50, 0.82), 5),
        "health": round(rng.uniform(0.78, 1.0), 5),
        "genes": genes,
        "infections": prevalence,
        "isolation_days": 0.0,
    }


def _initialize_population(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], eco: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    state = {
        "schema": VIVARIUM_SCHEMA_VERSION,
        "engine": "VIVARIUM",
        # Pre-2.0 PHYLUM generations did not represent a physical duration, so
        # VIVARIUM must not invent elapsed days for the old timeline.  Continuous
        # time begins at migration while Git's existing observation index and all
        # fossil history remain untouched.
        "sim_day": 0.0,
        "year_days": YEAR_DAYS,
        "checkpoint_days": DEFAULT_CHECKPOINT_DAYS,
        "next_organism_id": 1,
        "next_cohort_id": 1,
        "observation_index": int(world.get("generation", 0)),
        "epoch_origin_observation": int(world.get("generation", 0)),
        "legacy_observations": int(world.get("generation", 0)),
        "statistics": {},
        "last_checkpoint": {},
        "isolation": {},
    }
    agents: list[dict[str, Any]] = []
    cohorts: list[dict[str, Any]] = []
    living = _living(species)
    total_living = sum(max(0.0, float(sp.get("population", 0))) for sp in living)
    for sp in living:
        pop = max(0.0, float(sp.get("population", 0)))
        cells = _range_cells(sp)
        if pop <= 0:
            continue
        desired = int(min(MAX_AGENTS_PER_SPECIES, max(8, round(math.sqrt(pop) * 3.4)), math.floor(pop)))
        # Respect the global cap proportionally in unusually rich worlds.
        if total_living > 0 and len(living) * MAX_AGENTS_PER_SPECIES > MAX_TOTAL_AGENTS:
            desired = min(desired, max(4, int(MAX_TOTAL_AGENTS * pop / total_living)))
        for i in range(desired):
            cell = cells[i % len(cells)]
            agents.append(_founder_agent(world, state, sp, i, cell, eco))
        remainder = max(0.0, pop - desired)
        if remainder > 0:
            cohort_cells = cells[:MAX_COHORTS_PER_SPECIES]
            weights = [1.0 + ((stable_int(f"{sp.get('id')}:{c}") % 1000) / 2500.0) for c in cohort_cells]
            wsum = sum(weights) or 1.0
            allocated = 0.0
            for i, (cell, weight) in enumerate(zip(cohort_cells, weights)):
                count = remainder * weight / wsum
                if i == len(cohort_cells) - 1:
                    count = remainder - allocated
                allocated += count
                cohorts.append(_founder_cohort(world, state, sp, cell, count, i))
    return state, agents, cohorts


def reconcile_vivarium_lineages(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], plates: dict[str, Any], save: bool = True) -> int:
    """Materialize aggregate founder populations that entered after migration.

    Branch-contact is allowed to introduce a living lineage into an already-running
    VIVARIUM world.  Legacy contact code creates the aggregate species record first;
    this bridge converts only lineages with *no* living agent/cohort representation
    into explicit founders plus bounded cohorts.  Existing VIVARIUM populations are
    never rescaled here, so ordinary evolution remains authoritative.
    """
    state, agents, cohorts, eco = ensure_vivarium_state(world, species, env, plates, save=False)
    represented = Counter(str(a.get("species_id")) for a in agents if a.get("alive", True))
    for c in cohorts:
        if float(c.get("count", 0)) > 0:
            represented[str(c.get("species_id"))] += float(c.get("count", 0))
    live_agent_counts = Counter(str(a.get("species_id")) for a in agents if a.get("alive", True))
    live_cohort_counts = Counter(str(c.get("species_id")) for c in cohorts if float(c.get("count", 0)) > 0)
    total_live_agents = sum(live_agent_counts.values())
    introduced = 0
    for sp in _living(species):
        sid = str(sp.get("id"))
        target = max(0.0, float(sp.get("population", 0)))
        if target <= 0 or represented.get(sid, 0) > 0.03:
            continue
        cells = _range_cells(sp)
        room_species = max(0, MAX_AGENTS_PER_SPECIES - live_agent_counts[sid])
        room_global = max(0, MAX_TOTAL_AGENTS - total_live_agents)
        desired = int(min(room_species, room_global, max(4, round(math.sqrt(target) * 2.4)), math.floor(target)))
        for i in range(desired):
            cell = cells[i % len(cells)]
            a = _founder_agent(world, state, sp, int(state.get("next_organism_id", 1)) + i, cell, eco)
            a["origin"] = "branch-contact founder"
            agents.append(a)
        live_agent_counts[sid] += desired
        total_live_agents += desired
        remainder = max(0.0, target - desired)
        if remainder > 0:
            available_cells = cells[:max(1, MAX_COHORTS_PER_SPECIES - live_cohort_counts[sid])]
            weights = [1.0 + ((stable_int(f"contact:{sid}:{c}") % 1000) / 3000.0) for c in available_cells]
            wsum = sum(weights) or 1.0
            allocated = 0.0
            for i, (cell, weight) in enumerate(zip(available_cells, weights)):
                count = remainder * weight / wsum
                if i == len(available_cells) - 1:
                    count = remainder - allocated
                allocated += count
                cohorts.append(_founder_cohort(world, state, sp, cell, count, int(state.get("next_cohort_id", 1)) + i))
            live_cohort_counts[sid] += len(available_cells)
        represented[sid] = target
        introduced += 1
    if introduced:
        _sync_world_metadata(world, state, agents, cohorts)
        save_vivarium_state(state, agents, cohorts, eco)
    elif save:
        save_vivarium_state(state, agents, cohorts, eco)
    return introduced


def load_vivarium_state() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return (
        load_json(VIVARIUM_PATH, {}) or {},
        load_json(ORGANISMS_PATH, []) or [],
        load_json(COHORTS_PATH, []) or [],
        load_json(ECOSYSTEM_PATH, {}) or {},
    )


def save_vivarium_state(state: dict[str, Any], agents: list[dict[str, Any]], cohorts: list[dict[str, Any]], eco: dict[str, Any]) -> None:
    atomic_json(VIVARIUM_PATH, state)
    atomic_json(ORGANISMS_PATH, agents)
    atomic_json(COHORTS_PATH, cohorts)
    atomic_json(ECOSYSTEM_PATH, eco)


def ensure_vivarium_state(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], plates: dict[str, Any], save: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    state, agents, cohorts, eco = load_vivarium_state()
    if not eco or int(eco.get("schema", 0)) != VIVARIUM_SCHEMA_VERSION:
        eco = _initial_ecosystem(world, env, plates)
    if not state or int(state.get("schema", 0)) != VIVARIUM_SCHEMA_VERSION:
        state, agents, cohorts = _initialize_population(world, species, env, eco)
    state["schema"] = VIVARIUM_SCHEMA_VERSION
    state["engine"] = "VIVARIUM"
    state.setdefault("sim_day", float(world.get("generation", 0)) * DEFAULT_CHECKPOINT_DAYS)
    state.setdefault("year_days", YEAR_DAYS)
    state.setdefault("checkpoint_days", DEFAULT_CHECKPOINT_DAYS)
    state.setdefault("observation_index", int(world.get("generation", 0)))
    state.setdefault("next_organism_id", 1 + max([int(str(a.get("id", "o-0")).split("-")[-1]) for a in agents if str(a.get("id", "")).startswith("o-")] or [0]))
    state.setdefault("next_cohort_id", 1 + max([int(str(c.get("id", "c-0")).split("-")[-1]) for c in cohorts if str(c.get("id", "")).startswith("c-")] or [0]))
    state.setdefault("statistics", {})
    state.setdefault("last_checkpoint", {})
    state.setdefault("isolation", {})
    world["engine"] = "VIVARIUM"
    world["vivarium"] = {
        "schema": VIVARIUM_SCHEMA_VERSION,
        "sim_day": round(float(state.get("sim_day", 0.0)), 3),
        "sim_year": round(float(state.get("sim_day", 0.0)) / float(state.get("year_days", YEAR_DAYS)), 4),
        "checkpoint_days": int(state.get("checkpoint_days", DEFAULT_CHECKPOINT_DAYS)),
        "observation_index": int(state.get("observation_index", world.get("generation", 0))),
        "explicit_organisms": sum(1 for a in agents if a.get("alive", True)),
        "cohorts": len([c for c in cohorts if float(c.get("count", 0)) > 0]),
        "last_checkpoint": copy.deepcopy(state.get("last_checkpoint", {})),
    }
    if save:
        save_vivarium_state(state, agents, cohorts, eco)
    return state, agents, cohorts, eco


def _remember(agent: dict[str, Any], kind: str, cell: tuple[int, int], score: float, sim_day: float) -> None:
    memory = [m for m in agent.setdefault("memory", []) if isinstance(m, dict)]
    key = (kind, int(cell[0]), int(cell[1]))
    found = None
    for row in memory:
        if (row.get("kind"), int(row.get("cell", [0, 0])[0]), int(row.get("cell", [0, 0])[1])) == key:
            found = row
            break
    if found:
        found["score"] = round(clamp(float(found.get("score", 0)) * 0.65 + score * 0.35, 0, 1), 4)
        found["day"] = round(sim_day, 3)
    else:
        memory.append({"kind": kind, "cell": [cell[0], cell[1]], "score": round(clamp(score, 0, 1), 4), "day": round(sim_day, 3)})
    memory.sort(key=lambda m: (float(m.get("score", 0)), float(m.get("day", 0))), reverse=True)
    agent["memory"] = memory[:MAX_AGENT_MEMORY]


def _decay_memory(agent: dict[str, Any], capacity: float) -> None:
    keep = []
    retain = 0.985 + clamp(capacity, 0, 1) * 0.012
    for row in agent.get("memory", []):
        cp = dict(row)
        cp["score"] = round(float(cp.get("score", 0)) * retain, 4)
        if cp["score"] > 0.05:
            keep.append(cp)
    agent["memory"] = keep[:MAX_AGENT_MEMORY]


def _best_move(agent: dict[str, Any], eco: dict[str, Any], sp: dict[str, Any], rng: random.Random) -> tuple[int, int]:
    cur = _parse_cell(agent.get("cell", [0, 0]))
    options = [cur] + neighbors(cur)
    aquatic = float(agent.get("genes", {}).get("aquatic", 0.0))
    temp_pref = float(agent.get("genes", {}).get("temp_pref", 0.5))
    moist_pref = float(agent.get("genes", {}).get("moisture_pref", 0.5))
    memory_bonus: dict[tuple[int, int], float] = defaultdict(float)
    for row in agent.get("memory", []):
        cell = _parse_cell(row.get("cell", [0, 0]))
        if row.get("kind") == "food":
            memory_bonus[cell] += float(row.get("score", 0)) * 0.18
        elif row.get("kind") == "threat":
            memory_bonus[cell] -= float(row.get("score", 0)) * 0.24
    def score(cell: tuple[int, int]) -> float:
        st = eco.get("cells", {}).get(_cell_key(cell), {})
        if not st:
            return -9
        habitat = 1.0
        if bool(st.get("land", True)) and aquatic > 0.72:
            habitat = 0.22
        if not bool(st.get("land", True)) and aquatic < 0.28:
            habitat = 0.18
        climate = 1 - (abs(float(st.get("temperature", 0.5)) - temp_pref) + abs(float(st.get("moisture", 0.5)) - moist_pref)) * 0.55
        food = clamp(float(st.get("producer_biomass", 0)) / max(1.0, float(st.get("capacity", 1))), 0, 1)
        return habitat * (climate * 0.55 + food * 0.45) + memory_bonus[cell] + rng.random() * 0.025
    return max(options, key=score)


def _social_capacity(sp: dict[str, Any]) -> tuple[float, float, float]:
    nerve = sp.get("nerve", {})
    arch = nerve.get("architecture", {})
    social = nerve.get("social", {})
    techne = sp.get("techne", {})
    learning = clamp(float(arch.get("learning_rate", 0.05)), 0, 1)
    memory = clamp(float(arch.get("memory_capacity", 0.05)), 0, 1)
    transmission = clamp(float(techne.get("capacities", {}).get("transmission", 0.0)), 0, 1)
    return learning, memory, transmission


def _metabolic_cost(agent: dict[str, Any], sp: dict[str, Any]) -> float:
    g = agent.get("genes", {})
    body = max(0.04, float(agent.get("phenotype", {}).get("body_size", g.get("body_size", 1.0))))
    complexity = float(g.get("complexity", 0.05))
    mobility = float(g.get("mobility", 0.1))
    neural = float(sp.get("nerve", {}).get("architecture", {}).get("neural_complexity", complexity))
    # Intelligence and movement are not free upgrades.
    # Energy is a bounded condition reserve rather than literal calories.  The
    # daily maintenance scale must therefore be comparable with the gains below:
    # an adapted autotroph in an ordinary productive cell should be capable of
    # meeting maintenance, while large/mobile/neural organisms still pay a
    # meaningful premium.  Earlier VIVARIUM prototypes made basal maintenance
    # larger than photosynthetic gain and slowly starved every founder.
    return 0.0038 + math.log1p(body) * 0.0018 + mobility * 0.0018 + neural * 0.0028


def _agent_feed(agent: dict[str, Any], sp: dict[str, Any], cell_state: dict[str, Any], cohorts_in_cell: list[dict[str, Any]], agents_in_cell: list[dict[str, Any]], species_by_id: dict[str, dict[str, Any]], rng: random.Random, deaths: list[dict[str, Any]], kill_stats: dict[tuple[str, str], float], sim_day: float) -> float:
    g = agent.get("genes", {})
    autotrophy = float(g.get("autotrophy", 0))
    herbivory = float(g.get("herbivory", 0))
    carnivory = float(g.get("carnivory", 0))
    detritivory = float(g.get("detritivory", 0))
    gains: list[tuple[str, float]] = []
    if autotrophy > 0.05:
        # Autotrophy draws from climate/productivity rather than producer
        # biomass.  A strong producer can cover maintenance in suitable habitat,
        # but low productivity still turns photosynthesis into a poor strategy.
        light = clamp(float(cell_state.get("productivity", 0.2)), 0, 1.2)
        nutrients = clamp(float(cell_state.get("nutrients", 0.5)), 0, 1)
        moisture = clamp(float(cell_state.get("moisture", 0.5)), 0, 1)
        photo = 0.0055 + light * 0.014 + nutrients * 0.002 + moisture * 0.001
        gains.append(("autotrophy", autotrophy * photo))
    if herbivory > 0.04 and float(cell_state.get("producer_biomass", 0)) > 0:
        bite = min(float(cell_state.get("producer_biomass", 0)), 0.06 + herbivory * 0.13)
        cell_state["producer_biomass"] = round(max(0.0, float(cell_state.get("producer_biomass", 0)) - bite), 5)
        gains.append(("grazing", herbivory * bite * 0.18))
    if detritivory > 0.04 and float(cell_state.get("detritus", 0)) > 0:
        bite = min(float(cell_state.get("detritus", 0)), 0.04 + detritivory * 0.09)
        cell_state["detritus"] = round(max(0.0, float(cell_state.get("detritus", 0)) - bite), 5)
        gains.append(("detritus", detritivory * bite * 0.20))
    if carnivory > 0.18 and rng.random() < 0.06 + carnivory * 0.12:
        predator_id = str(agent.get("species_id"))
        candidates = [a for a in agents_in_cell if a.get("alive", True) and str(a.get("species_id")) != predator_id]
        # Prefer cohort prey when it dominates local abundance; this keeps explicit
        # agents representative rather than making them unrealistically fragile.
        cohort_prey = [c for c in cohorts_in_cell if str(c.get("species_id")) != predator_id and float(c.get("count", 0)) > 0.5]
        if cohort_prey and (not candidates or rng.random() < 0.72):
            prey = rng.choice(cohort_prey)
            prey_sp = species_by_id.get(str(prey.get("species_id")), {})
            defense = float(prey.get("genes", {}).get("defense", prey_sp.get("genome", {}).get("defense", 0.2)))
            success = clamp(0.18 + float(g.get("attack", 0.2)) * 0.48 + float(g.get("speed", 0.2)) * 0.18 - defense * 0.36, 0.02, 0.88)
            if rng.random() < success:
                killed = min(float(prey.get("count", 0)), max(0.2, 0.4 + float(g.get("body_size", 1.0)) * 0.15))
                prey["count"] = round(max(0.0, float(prey.get("count", 0)) - killed), 5)
                cell_state["detritus"] = round(float(cell_state.get("detritus", 0)) + killed * 0.025, 5)
                gains.append(("predation", min(0.24, 0.06 + carnivory * 0.14)))
                kill_stats[(predator_id, str(prey.get("species_id")))] += killed
        elif candidates:
            prey = rng.choice(candidates)
            pg = prey.get("genes", {})
            defense = float(pg.get("defense", 0.2)) + float(prey.get("phenotype", {}).get("speed", pg.get("speed", 0.2))) * 0.20
            attack = float(g.get("attack", 0.2)) + float(agent.get("phenotype", {}).get("speed", g.get("speed", 0.2))) * 0.18
            success = clamp(0.12 + attack * 0.48 - defense * 0.32, 0.02, 0.82)
            if rng.random() < success:
                prey["alive"] = False
                prey["cause_of_death"] = "predation"
                deaths.append({"organism_id": prey.get("id"), "species_id": prey.get("species_id"), "cause": "predation", "sim_day": sim_day})
                cell_state["detritus"] = round(float(cell_state.get("detritus", 0)) + max(0.02, float(pg.get("body_size", 1.0))) * 0.06, 5)
                gains.append(("predation", min(0.30, 0.08 + carnivory * 0.18)))
                kill_stats[(predator_id, str(prey.get("species_id")))] += 1.0
                _remember(prey, "threat", _parse_cell(agent.get("cell", [0, 0])), 0.9, sim_day)
    gain = sum(v for _, v in gains)
    if gain > 0.006:
        _remember(agent, "food", _parse_cell(agent.get("cell", [0, 0])), clamp(gain * 4.5, 0.08, 1.0), sim_day)
    return gain


def _inherit_genes(a: dict[str, Any], b: dict[str, Any], rng: random.Random) -> dict[str, float]:
    ga, gb = a.get("genes", {}), b.get("genes", {})
    recomb = clamp((float(ga.get("recombination", 0.4)) + float(gb.get("recombination", 0.4))) / 2, 0, 1)
    genes: dict[str, float] = {}
    for locus in GENE_LOCI:
        lo, hi = TRAIT_BOUNDS.get(locus, (0.0, 1.0))
        av, bv = float(ga.get(locus, (lo + hi) / 2)), float(gb.get(locus, (lo + hi) / 2))
        if rng.random() < recomb:
            base = av if rng.random() < 0.5 else bv
        else:
            base = (av + bv) / 2
        mutation = rng.gauss(0, (hi - lo) * (0.0012 + recomb * 0.0014))
        genes[locus] = round(clamp(base + mutation, lo, hi), 6)
    return genes


def _offspring_agent(world: dict[str, Any], state: dict[str, Any], parent_a: dict[str, Any], parent_b: dict[str, Any], sp: dict[str, Any], eco: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    genes = _inherit_genes(parent_a, parent_b, rng)
    cell = _parse_cell(parent_a.get("cell", [0, 0]))
    culture = []
    candidates = list(dict.fromkeys(list(parent_a.get("culture", [])) + list(parent_b.get("culture", []))))
    _, _, transmission = _social_capacity(sp)
    for item in candidates:
        if rng.random() < 0.25 + transmission * 0.50:
            culture.append(item)
    return {
        "id": _next_agent_id(state), "species_id": str(sp.get("id")), "origin": "birth",
        "born_day": round(float(state.get("sim_day", 0)), 3), "age_days": 0.0, "stage": "propagule",
        "sex": "A" if rng.random() < 0.5 else "B", "cell": [cell[0], cell[1]],
        "energy": 0.56, "health": 0.96, "genes": genes,
        "phenotype": _phenotype(genes, eco["cells"][_cell_key(cell)]),
        "parent_ids": [str(parent_a.get("id")), str(parent_b.get("id"))],
        "memory": [], "social": {}, "culture": culture[:6], "infections": {}, "alive": True, "cause_of_death": None,
    }


def _cohort_birth(cohorts: list[dict[str, Any]], state: dict[str, Any], sp: dict[str, Any], cell: tuple[int, int], count: float, parent_genes: dict[str, float], rng: random.Random) -> None:
    if count <= 0:
        return
    for c in cohorts:
        if str(c.get("species_id")) == str(sp.get("id")) and _parse_cell(c.get("cell", [0, 0])) == cell:
            old = float(c.get("count", 0))
            total = old + count
            if total <= 0:
                return
            for locus in GENE_LOCI:
                lo, hi = TRAIT_BOUNDS.get(locus, (0.0, 1.0))
                pv = float(parent_genes.get(locus, _base_gene(sp, locus)))
                nv = clamp(pv + rng.gauss(0, (hi - lo) * 0.0016), lo, hi)
                cv = float(c.get("genes", {}).get(locus, pv))
                c.setdefault("genes", {})[locus] = round((cv * old + nv * count) / total, 6)
            c["count"] = round(total, 5)
            c["mean_age_days"] = round(max(0.0, float(c.get("mean_age_days", 0)) * old / total), 3)
            return
    cohorts.append({
        "id": _next_cohort_id(state), "species_id": str(sp.get("id")), "cell": [cell[0], cell[1]],
        "count": round(count, 5), "mean_age_days": 0.0, "energy": 0.58, "health": 0.94,
        "genes": {k: round(float(parent_genes.get(k, _base_gene(sp, k))), 6) for k in GENE_LOCI},
        "infections": {}, "isolation_days": 0.0,
    })


def _resolve_agent_from_cohort(world: dict[str,Any], state: dict[str,Any], sp: dict[str,Any], cohort: dict[str,Any], eco: dict[str,Any], rng: random.Random) -> dict[str,Any]:
    """Promote one conceptual cohort member into high-fidelity agent state.

    This is a level-of-detail operation, not a birth. One unit is subtracted from
    the cohort and the exact same organism becomes explicit, preserving total
    population while ensuring a living lineage can regain individual resolution
    after its original explicit sample dies out.
    """
    genes={}
    for locus in GENE_LOCI:
        lo,hi=TRAIT_BOUNDS[locus]
        center=float(cohort.get("genes",{}).get(locus,_base_gene(sp,locus)))
        # Cohorts store an allele mean; resolve a plausible member with tiny
        # within-cohort variation rather than cloning the mean exactly.
        genes[locus]=round(clamp(center+rng.gauss(0,(hi-lo)*0.0035),lo,hi),6)
    cell=_parse_cell(cohort.get("cell",[0,0])); mean_age=max(0.0,float(cohort.get("mean_age_days",0)))
    life=_lifespan_days(genes,sp.get("soma")); age=clamp(rng.gauss(mean_age,max(4.0,life*0.08)),0,life*1.08)
    infections=[]
    infmap={}
    for pid,prev in cohort.get("infections",{}).items():
        if rng.random()<clamp(float(prev),0,1):
            infmap[str(pid)]=round(clamp(float(prev)+rng.gauss(0,.01),.001,.98),6)
    return {
        "id":_next_agent_id(state),"species_id":str(sp.get("id")),"origin":"cohort-resolution",
        "born_day":round(float(state.get("sim_day",0))-age,3),"age_days":round(age,3),"stage":_stage(age,genes,sp.get("soma")),
        "sex":"A" if rng.random()<.5 else "B","cell":[cell[0],cell[1]],
        "energy":round(clamp(float(cohort.get("energy",.6))+rng.gauss(0,.035),.15,1),5),
        "health":round(clamp(float(cohort.get("health",.9))+rng.gauss(0,.025),.15,1),5),
        "genes":genes,"phenotype":_phenotype(genes,eco["cells"][_cell_key(cell)]),"parent_ids":[],
        "memory":[],"social":{},"culture":[],"infections":infmap,"alive":True,"cause_of_death":None,
    }


def _rebalance_explicit_resolution(world: dict[str,Any], state: dict[str,Any], species: list[dict[str,Any]], agents: list[dict[str,Any]], cohorts: list[dict[str,Any]], eco: dict[str,Any], rng: random.Random) -> None:
    """Maintain bounded individual resolution without creating population."""
    by_sid_agents=Counter(str(a.get("species_id")) for a in agents if a.get("alive",True))
    total_agents=sum(by_sid_agents.values())
    for sp in sorted(_living(species),key=lambda s:str(s.get("id"))):
        sid=str(sp.get("id")); pop=max(0.0,float(sp.get("population",0)))
        if pop<1 or total_agents>=MAX_TOTAL_AGENTS: continue
        desired=int(min(MAX_AGENTS_PER_SPECIES,48,max(10,round(math.sqrt(pop)*2.25)),math.floor(pop)))
        current=int(by_sid_agents.get(sid,0))
        # Re-resolution only triggers after substantial loss of the explicit
        # sample, avoiding constant cohort<->agent churn.
        if current>=max(4,int(desired*.55)): continue
        need=min(desired-current,max(4,desired//4),MAX_TOTAL_AGENTS-total_agents)
        sources=sorted((c for c in cohorts if str(c.get("species_id"))==sid and float(c.get("count",0))>1.05),key=lambda c:float(c.get("count",0)),reverse=True)
        for _ in range(max(0,need)):
            if not sources: break
            source=max(sources,key=lambda c:float(c.get("count",0)))
            if float(source.get("count",0))<=1.05:
                sources=[c for c in sources if float(c.get("count",0))>1.05]
                if not sources: break
                source=max(sources,key=lambda c:float(c.get("count",0)))
            source["count"]=round(float(source.get("count",0))-1.0,5)
            agents.append(_resolve_agent_from_cohort(world,state,sp,source,eco,rng))
            by_sid_agents[sid]+=1; total_agents+=1


def _update_weather(eco: dict[str, Any], rng: random.Random) -> dict[str, float]:
    weather = eco.setdefault("weather", {})
    ta = clamp(float(weather.get("temperature_anomaly", 0.0)) * 0.78 + rng.gauss(0, 0.022), -0.18, 0.18)
    ra = clamp(float(weather.get("rain_anomaly", 0.0)) * 0.72 + rng.gauss(0, 0.035), -0.24, 0.24)
    storm = clamp(float(weather.get("storm", 0.0)) * 0.40 + max(0.0, abs(ra) - 0.12) * rng.uniform(0.5, 1.6), 0, 1)
    weather.update({"temperature_anomaly": round(ta, 5), "rain_anomaly": round(ra, 5), "storm": round(storm, 5)})
    return {"temperature_anomaly": ta, "rain_anomaly": ra, "storm": storm}


def _seasonal_anomalies(cell: tuple[int,int], sim_day: float) -> tuple[float,float]:
    """Return deterministic local seasonal temperature/moisture departures."""
    # Equatorial cells have weak seasons; higher latitudes have stronger and
    # opposite-phase seasons across hemispheres.  The 360-day VIVARIUM year is a
    # simulation convention, not a claim that PHYLUM's planet is Earth.
    _, y = cell
    latitude = ((y + 0.5) / max(1, GRID_ROWS) - 0.5) * 2.0
    amplitude = abs(latitude) ** 0.72
    phase = (float(sim_day) % YEAR_DAYS) / YEAR_DAYS * math.tau
    if latitude > 0:
        phase += math.pi
    temp = math.sin(phase) * 0.075 * amplitude
    rain = math.sin(phase + math.pi * 0.42) * 0.045 * amplitude
    return temp, rain


def _recalibrate_active_cells(world: dict[str, Any], env: dict[str, Any], plates: dict[str, Any], eco: dict[str, Any], active_cells: set[tuple[int, int]]) -> None:
    seed = int(world.get("seed", 0))
    for cell in active_cells:
        key = _cell_key(cell)
        fresh = _ecosystem_cell(env, plates, seed, cell)
        old = eco.setdefault("cells", {}).setdefault(key, fresh)
        # Planet change modifies climatic baselines without erasing accumulated
        # biomass, detritus or nutrient history.
        for k in ("temperature", "moisture", "productivity", "capacity", "water", "land", "elevation"):
            old[k] = fresh[k]
        old["producer_biomass"] = round(clamp(float(old.get("producer_biomass", fresh["producer_biomass"])), 0, float(old.get("capacity", fresh["capacity"])) * 1.25), 5)
        old["nutrients"] = round(clamp(float(old.get("nutrients", fresh["nutrients"])), 0.01, 1.0), 5)


def _grow_ecosystem(eco: dict[str, Any], active_cells: set[tuple[int, int]], weather: dict[str, float]) -> None:
    for cell in active_cells:
        st = eco.get("cells", {}).get(_cell_key(cell))
        if not st:
            continue
        capacity = max(1.0, float(st.get("capacity", 30.0)))
        biomass = max(0.0, float(st.get("producer_biomass", 0.0)))
        prod = max(0.01, float(st.get("productivity", 0.1)))
        engineering = clamp(float(st.get("engineering_pressure", 0.0)), 0, 0.35)
        seasonal_t,seasonal_r=_seasonal_anomalies(cell,float(weather.get("sim_day",0)))
        moisture = clamp(float(st.get("moisture", 0.5)) + weather["rain_anomaly"] * 0.28 + seasonal_r + engineering * 0.08, 0, 1)
        temp = clamp(float(st.get("temperature", 0.5)) + weather["temperature_anomaly"] + seasonal_t, 0, 1)
        stress = clamp(abs(temp - 0.56) * 0.55 + max(0.0, 0.22 - moisture) * 0.9, 0, 0.85)
        growth = prod * (0.16 + float(st.get("nutrients", 0.5)) * 0.18) * (1 - biomass / capacity) * (1 - stress) * (1 + engineering * 0.22)
        biomass = clamp(biomass + growth, 0, capacity * 1.25)
        det = max(0.0, float(st.get("detritus", 0)))
        decomposition = min(det, 0.012 + moisture * 0.022 + temp * 0.016)
        det -= decomposition
        nutrients = clamp(float(st.get("nutrients", 0.4)) + decomposition * 0.028 - growth * 0.003 + engineering * 0.00012, 0.02, 1.0)
        st["producer_biomass"] = round(biomass, 5)
        st["detritus"] = round(det, 5)
        st["nutrients"] = round(nutrients, 5)


def _update_biotic_engineering(agents: list[dict[str, Any]], cohorts: list[dict[str, Any]], eco: dict[str, Any], active_cells: set[tuple[int, int]]) -> None:
    """Accumulate habitat modification from organisms that physically occupy cells."""
    pressure: defaultdict[tuple[int,int], float] = defaultdict(float)
    for c in cohorts:
        count=max(0.0,float(c.get("count",0)))
        if count<=0: continue
        eng=clamp(float(c.get("genes",{}).get("engineering",0)),0,1)
        if eng<0.18: continue
        pressure[_parse_cell(c.get("cell",[0,0]))] += eng * math.log1p(count) * 0.00022
    for a in agents:
        if not a.get("alive",True): continue
        eng=clamp(float(a.get("genes",{}).get("engineering",0)),0,1)
        if eng<0.18: continue
        cultural=1.0+min(0.35,len(a.get("culture",[]))*0.035)
        pressure[_parse_cell(a.get("cell",[0,0]))] += eng * cultural * 0.00008
    touched=active_cells|set(pressure)
    for cell in touched:
        st=eco.get("cells",{}).get(_cell_key(cell))
        if not st: continue
        old=float(st.get("engineering_pressure",0))*0.997
        st["engineering_pressure"]=round(clamp(old+pressure.get(cell,0),0,0.35),6)


def _publish_biotic_modifiers(env: dict[str,Any], eco: dict[str,Any], active_cells: set[tuple[int,int]]) -> None:
    """Expose local VIVARIUM engineering to PALEON/ORRERY compatibility layers."""
    rows=[]
    for x,y in sorted(active_cells):
        st=eco.get("cells",{}).get(_cell_key((x,y)),{})
        strength=clamp(float(st.get("engineering_pressure",0)),0,0.35)
        if strength<0.008: continue
        rows.append({"x":x,"y":y,"strength":round(strength*0.55,6),"moisture":round(strength*0.12,6),"source":"VIVARIUM"})
    rows.sort(key=lambda r:float(r.get("strength",0)),reverse=True)
    env["biotic_modifiers"]=rows[:1200]


def _cohort_daily_step(world: dict[str, Any], state: dict[str, Any], cohorts: list[dict[str, Any]], species_by_id: dict[str, dict[str, Any]], eco: dict[str, Any], weather: dict[str, float], rng: random.Random, births: defaultdict[str, float], deaths_by_species: defaultdict[str, float], causes: dict[str, Counter], competition_stats: dict[tuple[str, str], float]) -> None:
    by_cell: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for c in cohorts:
        if float(c.get("count", 0)) > 0.001 and str(c.get("species_id")) in species_by_id:
            by_cell[_parse_cell(c.get("cell", [0, 0]))].append(c)
    spawned: list[dict[str, Any]] = []
    for cell, rows in by_cell.items():
        st = eco.get("cells", {}).get(_cell_key(cell), {})
        if not st:
            continue
        total_consumption = 0.0
        grazers: list[tuple[dict[str, Any], float]] = []
        for c in rows:
            sp = species_by_id.get(str(c.get("species_id")))
            if not sp:
                continue
            count = max(0.0, float(c.get("count", 0)))
            g = c.get("genes", {})
            herb = float(g.get("herbivory", 0))
            body = max(0.05, float(g.get("body_size", 1.0)))
            demand = count * herb * math.sqrt(body) * 0.0009
            if demand > 0:
                grazers.append((c, demand))
                total_consumption += demand
        biomass = float(st.get("producer_biomass", 0))
        if total_consumption > 0:
            consumed = min(biomass, total_consumption)
            st["producer_biomass"] = round(max(0.0, biomass - consumed), 5)
            # Competition is observed when multiple species draw from the same finite resource.
            ids = sorted({str(c.get("species_id")) for c, _ in grazers})
            if len(ids) > 1 and consumed < total_consumption * 0.92:
                for i, a in enumerate(ids):
                    for b in ids[i+1:]:
                        competition_stats[(a, b)] += 1 - consumed / max(total_consumption, 1e-9)
        for c in rows:
            sp = species_by_id.get(str(c.get("species_id")))
            if not sp:
                continue
            sid = str(sp.get("id"))
            count = max(0.0, float(c.get("count", 0)))
            if count <= 0:
                continue
            g = c.get("genes", {})
            cell_food = clamp(float(st.get("producer_biomass", 0)) / max(1.0, float(st.get("capacity", 1))), 0, 1)
            auto = float(g.get("autotrophy", 0)) * float(st.get("productivity", 0.1))
            herb = float(g.get("herbivory", 0)) * cell_food
            det = float(g.get("detritivory", 0)) * clamp(float(st.get("detritus", 0)) / 10.0, 0, 1)
            # A cohort's energy target represents whether its trophic strategy
            # can meet maintenance in this particular cell.  Do not multiply
            # autotrophy by productivity twice: doing so made even healthy
            # producer lineages converge on chronic starvation despite nearly
            # full local biomass.  Consumers remain dependent on finite food;
            # carnivores receive additional energy only from actual kills below.
            productivity = clamp(float(st.get("productivity", 0.1)), 0, 1.2)
            nutrients = clamp(float(st.get("nutrients", 0.4)), 0, 1)
            moisture = clamp(float(st.get("moisture", 0.5)), 0, 1)
            auto_capacity = float(g.get("autotrophy", 0)) * clamp(0.52 + productivity * 0.55 + nutrients * 0.12 + moisture * 0.06, 0.18, 1.0)
            herb_capacity = float(g.get("herbivory", 0)) * cell_food
            det_capacity = float(g.get("detritivory", 0)) * clamp(float(st.get("detritus", 0)) / max(3.0, float(st.get("capacity", 1)) * 0.10), 0, 1)
            resource = clamp(0.22 + auto_capacity * 0.68 + herb_capacity * 0.48 + det_capacity * 0.38, 0.06, 0.96)
            c["energy"] = round(clamp(float(c.get("energy", 0.6)) * 0.88 + resource * 0.12, 0, 1), 5)
            seasonal_t,seasonal_r=_seasonal_anomalies(cell,float(state.get("sim_day",0)))
            temp_stress = abs(float(st.get("temperature", 0.5)) + weather["temperature_anomaly"] + seasonal_t - float(g.get("temp_pref", 0.5)))
            moist_stress = abs(float(st.get("moisture", 0.5)) + weather["rain_anomaly"] * 0.2 + seasonal_r - float(g.get("moisture_pref", 0.5)))
            tolerance = max(0.08, float(g.get("tolerance", 0.25)))
            climate_stress = clamp((temp_stress + moist_stress) / (tolerance * 2.3), 0, 1)
            lifespan = _lifespan_days(g, sp.get("soma"))
            baseline = 1.0 / max(70.0, lifespan) * 0.52
            starvation = max(0.0, 0.28 - float(c.get("energy", 0.5))) * 0.024
            # Ordinary sub-optimal habitat lowers reproduction before it kills.
            # Direct climate mortality appears only beyond a meaningful stress
            # threshold, allowing tolerance/local adaptation to matter.
            climate_mort = max(0.0, climate_stress - 0.46) ** 1.7 * 0.00155
            storm_mort = weather["storm"] * (0.0011 + (1 - float(g.get("burrowing", 0))) * 0.0014)
            infection_mort = 0.0
            for pid, prev in list(c.setdefault("infections", {}).items()):
                p = next((p for p in world.get("_vivarium_pathogens", []) if str(p.get("id")) == str(pid)), None)
                if p:
                    infection_mort += float(prev) * float(p.get("virulence", 0.1)) * (1 - float(g.get("immune", 0.4)) * 0.65) * 0.004
            mortality_rate = clamp(baseline + starvation + climate_mort + storm_mort + infection_mort, 0, 0.18)
            died = min(count, count * mortality_rate)
            if died > 0:
                c["count"] = round(max(0.0, count - died), 5)
                deaths_by_species[sid] += died
                dominant = "disease" if infection_mort > max(starvation, climate_mort, baseline) else "starvation" if starvation > max(climate_mort, baseline) else "weather" if storm_mort + climate_mort > baseline else "age"
                causes[sid][dominant] += died
                st["detritus"] = round(float(st.get("detritus", 0)) + died * max(0.03, float(g.get("body_size", 1.0))) * 0.004, 5)
            survivors = max(0.0, float(c.get("count", 0)))
            if survivors <= 0:
                continue
            c["mean_age_days"] = round(float(c.get("mean_age_days", 0)) + 1.0, 3)
            fec = float(g.get("fecundity", 0.4))
            mature_fraction = clamp(0.35 + fec * 0.30 - climate_stress * 0.20, 0.05, 0.82)
            tech = float(sp.get("techne", {}).get("modifiers", {}).get("energy_efficiency", 1.0))
            social = float(sp.get("socius", {}).get("modifiers", {}).get("demography", 1.0))
            energy = float(c.get("energy", 0.5))
            energy_factor = clamp((energy - 0.28) / 0.42, 0.05, 1.25)
            # Reproductive tempo scales with life history.  This gives a lineage
            # enough lifetime reproductive opportunity to replace itself without
            # granting short- or long-lived organisms a free demographic win.
            lifetime_output = 0.92 + fec * 1.85
            climate_fertility = clamp(1.08 - climate_stress * 0.55, 0.20, 1.08)
            local_load = sum(float(r.get("count", 0)) for r in rows)
            carrying = max(12.0, float(st.get("capacity", 30.0)) * (0.72 + productivity * 0.55))
            density_factor = clamp(1.18 - local_load / carrying * 0.52, 0.22, 1.18)
            birth_rate = clamp((lifetime_output / max(70.0, lifespan)) * mature_fraction * energy_factor * climate_fertility * density_factor * tech * social, 0, 0.018)
            born = survivors * birth_rate
            if born > 0:
                c["count"] = round(survivors + born, 5)
                births[sid] += born
                # newborn contribution shifts mean age downward and permits heritable drift
                c["mean_age_days"] = round(float(c.get("mean_age_days", 0)) * survivors / max(0.001, survivors + born), 3)
            # Local selection changes cohort allele means through differential survival and reproduction.
            local_targets = {"temp_pref": float(st.get("temperature", 0.5)), "moisture_pref": float(st.get("moisture", 0.5))}
            for locus, target in local_targets.items():
                lo, hi = TRAIT_BOUNDS[locus]
                current = float(g.get(locus, target))
                g[locus] = round(clamp(current + (target - current) * 0.00018 * (1 - climate_stress * 0.4) + rng.gauss(0, (hi - lo) * 0.00005), lo, hi), 6)
            # Small populations drift faster.
            drift_scale = 0.00010 / max(1.0, math.sqrt(survivors / 10.0))
            for locus in ("immune", "speed", "defense", "sensory", "complexity", "sociality"):
                lo, hi = TRAIT_BOUNDS[locus]
                g[locus] = round(clamp(float(g.get(locus, (lo+hi)/2)) + rng.gauss(0, (hi-lo) * drift_scale), lo, hi), 6)
            c["genes"] = g
            # Range movement occurs as organisms move, not because the species object expands itself.
            mobility = float(g.get("mobility", 0))
            if survivors > 8 and rng.random() < 0.012 + mobility * 0.028:
                opts = neighbors(cell)
                if opts:
                    def quality(n: tuple[int, int]) -> float:
                        ns = eco.get("cells", {}).get(_cell_key(n), {})
                        if not ns: return -1
                        return clamp(float(ns.get("producer_biomass",0))/max(1,float(ns.get("capacity",1))),0,1) - abs(float(ns.get("temperature",.5))-float(g.get("temp_pref",.5)))*0.35 + rng.random()*0.04
                    dest = max(opts, key=quality)
                    moved = min(float(c.get("count", 0)) * clamp(0.015 + mobility * 0.025, 0.01, 0.06), max(0.5, float(c.get("count",0))-0.1))
                    if moved > 0.1:
                        c["count"] = round(max(0.0, float(c.get("count",0)) - moved),5)
                        cp = copy.deepcopy(c)
                        cp["id"] = _next_cohort_id(state)
                        cp["cell"] = [dest[0],dest[1]]
                        cp["count"] = round(moved,5)
                        cp["isolation_days"] = 0.0
                        spawned.append(cp)
    cohorts.extend(spawned)


def _cohort_predation(cohorts: list[dict[str, Any]], species_by_id: dict[str, dict[str, Any]], eco: dict[str, Any], rng: random.Random, deaths_by_species: defaultdict[str, float], causes: dict[str, Counter], kill_stats: dict[tuple[str, str], float]) -> None:
    by_cell: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for c in cohorts:
        if float(c.get("count",0)) > 0.2:
            by_cell[_parse_cell(c.get("cell",[0,0]))].append(c)
    for cell, rows in by_cell.items():
        predators = [c for c in rows if float(c.get("genes",{}).get("carnivory",0)) > 0.22 and float(c.get("count",0)) > 0]
        prey_rows = [c for c in rows if float(c.get("count",0)) > 0]
        for pred in predators:
            pid = str(pred.get("species_id"))
            pg = pred.get("genes",{})
            options = [x for x in prey_rows if str(x.get("species_id")) != pid and float(x.get("count",0)) > 0.5]
            if not options:
                continue
            prey = rng.choice(options)
            qid = str(prey.get("species_id"))
            qg = prey.get("genes",{})
            encounter = min(float(pred.get("count",0)), 120.0) * float(pg.get("carnivory",0)) * 0.0022
            success = clamp(0.20 + float(pg.get("attack",0.2))*0.35 + float(pg.get("speed",0.2))*0.15 - float(qg.get("defense",0.2))*0.25 - float(qg.get("speed",0.2))*0.10,0.02,0.78)
            killed = min(float(prey.get("count",0)), encounter * success)
            if killed <= 0:
                continue
            prey["count"] = round(max(0.0,float(prey.get("count",0))-killed),5)
            pred["energy"] = round(clamp(float(pred.get("energy",0.5))+killed/max(1,float(pred.get("count",1)))*0.09,0,1),5)
            deaths_by_species[qid] += killed
            causes[qid]["predation"] += killed
            kill_stats[(pid,qid)] += killed
            st=eco.get("cells",{}).get(_cell_key(cell),{})
            if st: st["detritus"]=round(float(st.get("detritus",0))+killed*max(0.03,float(qg.get("body_size",1)))*0.003,5)


def _pathogen_daily(world: dict[str, Any], state: dict[str, Any], species: list[dict[str, Any]], pathogens: list[dict[str, Any]], agents: list[dict[str, Any]], cohorts: list[dict[str, Any]], rng: random.Random, deaths_by_species: defaultdict[str, float], causes: dict[str, Counter]) -> None:
    living_ids = {str(s.get("id")) for s in _living(species)}
    by_cell_cohorts: dict[tuple[int,int], list[dict[str,Any]]] = defaultdict(list)
    for c in cohorts:
        if float(c.get("count",0))>0: by_cell_cohorts[_parse_cell(c.get("cell",[0,0]))].append(c)
    by_cell_agents: dict[tuple[int,int], list[dict[str,Any]]] = defaultdict(list)
    for a in agents:
        if a.get("alive",True): by_cell_agents[_parse_cell(a.get("cell",[0,0]))].append(a)
    for p in pathogens:
        if p.get("extinct_generation") is not None:
            continue
        pid=str(p.get("id")); trans=clamp(float(p.get("transmissibility",0.2)),0,1); vir=clamp(float(p.get("virulence",0.1)),0,1); breadth=clamp(float(p.get("host_breadth",0.1)),0,1)
        host_weight: defaultdict[str,float]=defaultdict(float); host_infected: defaultdict[str,float]=defaultdict(float)
        for cell, rows in by_cell_cohorts.items():
            infectious=sum(float(c.get("count",0))*float(c.get("infections",{}).get(pid,0)) for c in rows)
            total=sum(float(c.get("count",0)) for c in rows)
            local_pressure=clamp(infectious/max(1,total),0,1)
            for c in rows:
                sid=str(c.get("species_id")); count=float(c.get("count",0)); prev=float(c.setdefault("infections",{}).get(pid,0)); immune=float(c.get("genes",{}).get("immune",0.4))
                seeded = sid in p.get("hosts",{}) or prev>0
                if not seeded and local_pressure>0 and rng.random() < breadth*trans*local_pressure*0.035:
                    prev=rng.uniform(0.001,0.006)
                exposure=local_pressure*trans*(1-immune*0.55)
                recovery=0.018+immune*0.035
                prev=clamp(prev+(exposure-recovery)*prev*(1-prev),0,0.98)
                if prev<0.0005: c["infections"].pop(pid,None); prev=0
                else: c["infections"][pid]=round(prev,6)
                died=min(float(c.get("count",0)),count*prev*vir*(1-immune*0.45)*0.0016)
                if died>0:
                    c["count"]=round(max(0,float(c.get("count",0))-died),5); deaths_by_species[sid]+=died; causes[sid]["disease"]+=died
                host_weight[sid]+=count; host_infected[sid]+=count*prev
        for cell, rows in by_cell_agents.items():
            local_prev=[]
            for c in by_cell_cohorts.get(cell,[]):
                if float(c.get("count",0))>0: local_prev.append(float(c.get("infections",{}).get(pid,0)))
            pressure=max(local_prev or [0.0])
            for a in rows:
                sid=str(a.get("species_id")); immune=float(a.get("phenotype",{}).get("immune",a.get("genes",{}).get("immune",.4))); load=float(a.setdefault("infections",{}).get(pid,0))
                if load<=0 and pressure>0 and rng.random()<pressure*trans*(1-immune)*0.06:
                    load=rng.uniform(0.05,0.18)
                if load>0:
                    load=clamp(load+trans*0.025*(1-load)-immune*0.032,0,1)
                    if load<0.02: a["infections"].pop(pid,None)
                    else: a["infections"][pid]=round(load,5); a["health"]=round(clamp(float(a.get("health",1))-load*vir*0.005,0,1),5)
                    host_weight[sid]+=1; host_infected[sid]+=load
        hosts={sid:round(host_infected[sid]/max(1e-9,host_weight[sid]),6) for sid in host_weight if host_infected[sid]>0 and sid in living_ids}
        p["hosts"]=hosts
        p["peak_prevalence"]=round(max(float(p.get("peak_prevalence",0)),max(hosts.values(),default=0)),6)
    # Emergence is rare and conditioned on a large/contact-rich biosphere.
    total_pop=sum(float(s.get("population",0)) for s in _living(species))
    if len(pathogens)<48 and total_pop>120 and rng.random()<min(0.0045,0.00035+total_pop/2_000_000):
        host=rng.choice(_living(species)) if _living(species) else None
        if host:
            n=int(world.get("next_pathogen_id",1)); world["next_pathogen_id"]=n+1; pid=f"pa-{n:05d}"
            name=f"{['ashen','glass','pale','silent','cold'][rng.randrange(5)]} {['rot','fever','blight','flux','spore'][rng.randrange(5)]}"
            p={"id":pid,"name":name,"born_generation":int(world.get("generation",0)),"born_sim_day":round(float(state.get("sim_day",0)),3),"extinct_generation":None,"transmissibility":round(rng.uniform(.08,.30),5),"virulence":round(rng.uniform(.03,.20),5),"host_breadth":round(rng.uniform(.04,.25),5),"mutation_rate":round(rng.uniform(.015,.10),5),"environmental_persistence":round(rng.uniform(.02,.25),5),"hosts":{str(host.get("id")):0.004},"reservoirs":[str(host.get("id"))],"peak_prevalence":0.004}
            pathogens.append(p)
            world.setdefault("_vivarium_new_pathogens",[]).append(p)


def _agent_daily_step(world: dict[str, Any], state: dict[str, Any], agents: list[dict[str, Any]], cohorts: list[dict[str, Any]], species_by_id: dict[str, dict[str, Any]], eco: dict[str, Any], weather: dict[str, float], rng: random.Random, births: defaultdict[str, float], deaths_by_species: defaultdict[str, float], causes: dict[str, Counter], birth_records: list[dict[str, Any]], death_records: list[dict[str, Any]], kill_stats: dict[tuple[str, str], float]) -> None:
    alive = [a for a in agents if a.get("alive", True) and str(a.get("species_id")) in species_by_id]
    by_cell_agents: dict[tuple[int,int], list[dict[str,Any]]] = defaultdict(list)
    by_cell_cohorts: dict[tuple[int,int], list[dict[str,Any]]] = defaultdict(list)
    for a in alive: by_cell_agents[_parse_cell(a.get("cell",[0,0]))].append(a)
    for c in cohorts:
        if float(c.get("count",0))>0: by_cell_cohorts[_parse_cell(c.get("cell",[0,0]))].append(c)
    newborns=[]
    explicit_counts=Counter(str(a.get("species_id")) for a in alive)
    for agent in list(alive):
        if not agent.get("alive", True):
            continue
        sp=species_by_id.get(str(agent.get("species_id")))
        if not sp: continue
        sid=str(sp.get("id")); g=agent.get("genes",{}); cell=_parse_cell(agent.get("cell",[0,0])); st=eco.get("cells",{}).get(_cell_key(cell))
        if not st: continue
        learning,memory_cap,transmission=_social_capacity(sp)
        _decay_memory(agent,memory_cap)
        agent["age_days"]=round(float(agent.get("age_days",0))+1,3)
        agent["stage"]=_stage(float(agent["age_days"]),g,sp.get("soma"))
        agent["phenotype"]=_phenotype(g,st)
        cost=_metabolic_cost(agent,sp)
        gain=_agent_feed(agent,sp,st,by_cell_cohorts.get(cell,[]),by_cell_agents.get(cell,[]),species_by_id,rng,death_records,kill_stats,float(state.get("sim_day",0)))
        agent["energy"]=round(clamp(float(agent.get("energy",0.6))-cost+gain,0,1),5)
        seasonal_t,seasonal_r=_seasonal_anomalies(cell,float(state.get("sim_day",0)))
        temp=float(st.get("temperature",.5))+weather["temperature_anomaly"]+seasonal_t
        moist=float(st.get("moisture",.5))+weather["rain_anomaly"]*.2+seasonal_r
        tol=max(.08,float(g.get("tolerance",.25))); stress=clamp((abs(temp-float(g.get("temp_pref",.5)))+abs(moist-float(g.get("moisture_pref",.5))))/(tol*2.4),0,1)
        energy_now=float(agent.get("energy",0))
        health=float(agent.get("health",1))
        if energy_now<.18:
            health-=(.18-energy_now)*.035
        # Adapted, fed organisms recover from ordinary physiological wear.  Only
        # substantial mismatch creates persistent climate damage; without this
        # recovery term every explicit founder eventually lost health even in a
        # stable habitat.
        health += max(0.0, energy_now-.46)*.0018
        health -= max(0.0, stress-.48)*.0016 + weather["storm"]*.0007
        agent["health"]=round(clamp(health,0,1),5)
        # Movement emerges from an individual's condition and memory.
        move_drive=clamp((.52-float(agent.get("energy",.5)))*.35+float(g.get("mobility",0))*.12+learning*.025,0,.18)
        if rng.random()<move_drive:
            dest=_best_move(agent,eco,sp,rng)
            if dest!=cell:
                agent["cell"]=[dest[0],dest[1]]; cell=dest
        # Familiarity and cultural copying occur between particular individuals.
        peers=[p for p in by_cell_agents.get(cell,[]) if p.get("alive",True) and p.get("id")!=agent.get("id") and str(p.get("species_id"))==sid]
        if peers and float(g.get("sociality",0))>0.12:
            peer=rng.choice(peers); social=agent.setdefault("social",{}); pid=str(peer.get("id")); social[pid]=round(clamp(float(social.get(pid,0))+0.02+float(g.get("sociality",0))*.015,0,1),4)
            if len(social)>MAX_AGENT_SOCIAL:
                keep=sorted(social.items(),key=lambda kv:kv[1],reverse=True)[:MAX_AGENT_SOCIAL]; agent["social"]={k:v for k,v in keep}
            missing=[x for x in peer.get("culture",[]) if x not in agent.get("culture",[])]
            if missing and rng.random()<transmission*learning*.045:
                agent.setdefault("culture",[]).append(rng.choice(missing)); agent["culture"]=agent["culture"][-6:]
        # Actual reproduction requires a mature, sufficiently energetic organism and a compatible mate.
        life=_lifespan_days(g,sp.get("soma")); maturity=_maturity_days(g,sp.get("soma"))
        fec=float(g.get("fecundity",.4))
        reproductive_days=max(60.0,life-maturity)
        # Only one sex initiates the birth event, preventing a pair from being
        # counted twice.  Lifetime output is heritable through fecundity and the
        # life-history clock rather than a universal per-day magic number.
        daily_repro=clamp((1.7+fec*4.2)/reproductive_days,0.00015,0.018)
        if agent.get("stage")=="adult" and agent.get("sex")=="A" and float(agent.get("energy",0))>.59 and rng.random()<daily_repro:
            mates=[p for p in peers if p.get("stage")=="adult" and p.get("sex")!=agent.get("sex") and float(p.get("energy",0))>.58]
            if mates:
                mate=rng.choice(mates)
                child=_offspring_agent(world,state,agent,mate,sp,eco,rng)
                if explicit_counts[sid]<MAX_AGENTS_PER_SPECIES and len(alive)+len(newborns)<MAX_TOTAL_AGENTS:
                    newborns.append(child); explicit_counts[sid]+=1
                    birth_records.append({"organism_id":child["id"],"species_id":sid,"parent_ids":child["parent_ids"],"sim_day":float(state.get("sim_day",0))})
                else:
                    _cohort_birth(cohorts,state,sp,cell,1.0,child["genes"],rng)
                births[sid]+=1.0
                agent["energy"]=round(clamp(float(agent.get("energy",0))-.08,0,1),5); mate["energy"]=round(clamp(float(mate.get("energy",0))-.05,0,1),5)
        # Death is an organismal outcome rather than an aggregate multiplier.
        age=float(agent.get("age_days",0)); death_cause=None
        if float(agent.get("health",1))<=0.01: death_cause="disease" if agent.get("infections") else "starvation" if float(agent.get("energy",0))<.1 else "environment"
        elif age>life and rng.random()<clamp((age-life)/max(30,life)*.18+.03,0,0.40): death_cause="age"
        elif weather["storm"]>.65 and rng.random()<weather["storm"]*.0009: death_cause="weather"
        if death_cause:
            agent["alive"]=False; agent["cause_of_death"]=death_cause; deaths_by_species[sid]+=1; causes[sid][death_cause]+=1
            death_records.append({"organism_id":agent.get("id"),"species_id":sid,"cause":death_cause,"sim_day":float(state.get("sim_day",0))})
            st["detritus"]=round(float(st.get("detritus",0))+max(.03,float(g.get("body_size",1)))*.05,5)
    agents.extend(newborns)


def _merge_and_bound_cohorts(cohorts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str,tuple[int,int]], list[dict[str,Any]]] = defaultdict(list)
    for c in cohorts:
        count=float(c.get("count",0))
        if count>0.03:
            grouped[(str(c.get("species_id")),_parse_cell(c.get("cell",[0,0])))].append(c)
    merged=[]
    for (sid,cell),rows in grouped.items():
        if len(rows)==1:
            merged.append(rows[0]); continue
        total=sum(float(r.get("count",0)) for r in rows)
        base=copy.deepcopy(max(rows,key=lambda r:float(r.get("count",0))))
        base["count"]=round(total,5)
        for locus in GENE_LOCI:
            base.setdefault("genes",{})[locus]=round(sum(float(r.get("genes",{}).get(locus,0))*float(r.get("count",0)) for r in rows)/max(total,1e-9),6)
        pids={str(k) for r in rows for k in r.get("infections",{}).keys()}
        base["infections"]={pid:round(sum(float(r.get("infections",{}).get(pid,0))*float(r.get("count",0)) for r in rows)/max(total,1e-9),6) for pid in pids}
        base["mean_age_days"]=round(sum(float(r.get("mean_age_days",0))*float(r.get("count",0)) for r in rows)/max(total,1e-9),3)
        merged.append(base)
    # If a highly mobile lineage fragments into too many cohort cells, retain the
    # largest cells and merge the smallest into their nearest retained cell.
    by_sid: dict[str,list[dict[str,Any]]]=defaultdict(list)
    for c in merged: by_sid[str(c.get("species_id"))].append(c)
    bounded=[]
    for sid,rows in by_sid.items():
        rows.sort(key=lambda c:float(c.get("count",0)),reverse=True)
        keep=rows[:MAX_COHORTS_PER_SPECIES]; spill=rows[MAX_COHORTS_PER_SPECIES:]
        for c in spill:
            if not keep: keep.append(c); continue
            cell=_parse_cell(c.get("cell",[0,0])); target=min(keep,key=lambda k:math.dist(cell,_parse_cell(k.get("cell",[0,0]))))
            old=float(target.get("count",0)); add=float(c.get("count",0)); total=old+add
            for locus in GENE_LOCI:
                target.setdefault("genes",{})[locus]=round((float(target.get("genes",{}).get(locus,0))*old+float(c.get("genes",{}).get(locus,0))*add)/max(total,1e-9),6)
            target["count"]=round(total,5)
        bounded.extend(keep)
    return bounded


def _update_pathogen_summary(species: list[dict[str, Any]], pathogens: list[dict[str, Any]], agents: list[dict[str, Any]], cohorts: list[dict[str, Any]]) -> None:
    by_sid_agents: dict[str,list[dict[str,Any]]]=defaultdict(list); by_sid_cohorts: dict[str,list[dict[str,Any]]]=defaultdict(list)
    for a in agents:
        if a.get("alive",True): by_sid_agents[str(a.get("species_id"))].append(a)
    for c in cohorts:
        if float(c.get("count",0))>0: by_sid_cohorts[str(c.get("species_id"))].append(c)
    for sp in species:
        sid=str(sp.get("id")); pids={str(p.get("id")) for p in pathogens if p.get("extinct_generation") is None}; summary={}
        total=len(by_sid_agents[sid])+sum(float(c.get("count",0)) for c in by_sid_cohorts[sid])
        if total<=0: sp["infections"]={}; continue
        for pid in pids:
            infected=sum(float(a.get("infections",{}).get(pid,0)) for a in by_sid_agents[sid])
            infected+=sum(float(c.get("count",0))*float(c.get("infections",{}).get(pid,0)) for c in by_sid_cohorts[sid])
            prev=infected/total
            if prev>.0004: summary[pid]=round(prev,6)
        sp["infections"]=summary
    for p in pathogens:
        if p.get("extinct_generation") is not None: continue
        hosts={str(sp.get("id")):float(sp.get("infections",{}).get(str(p.get("id")),0)) for sp in species if float(sp.get("infections",{}).get(str(p.get("id")),0))>.0004}
        p["hosts"]={k:round(v,6) for k,v in hosts.items()}; p["peak_prevalence"]=round(max(float(p.get("peak_prevalence",0)),max(hosts.values(),default=0)),6)


def _population_rows(species: list[dict[str, Any]], agents: list[dict[str, Any]], cohorts: list[dict[str, Any]]) -> tuple[dict[str,float],dict[str,set[tuple[int,int]]]]:
    pops=defaultdict(float); cells: dict[str,set[tuple[int,int]]]=defaultdict(set)
    for a in agents:
        if not a.get("alive",True): continue
        sid=str(a.get("species_id")); pops[sid]+=1.0; cells[sid].add(_parse_cell(a.get("cell",[0,0])))
    for c in cohorts:
        n=max(0,float(c.get("count",0)))
        if n<=0: continue
        sid=str(c.get("species_id")); pops[sid]+=n; cells[sid].add(_parse_cell(c.get("cell",[0,0])))
    return dict(pops),cells


def _sync_species_from_population(world: dict[str, Any], species: list[dict[str, Any]], agents: list[dict[str, Any]], cohorts: list[dict[str, Any]], births: dict[str,float], deaths: dict[str,float], causes: dict[str,Counter]) -> None:
    pops,cells=_population_rows(species,agents,cohorts)
    by_sid_agents: dict[str,list[dict[str,Any]]]=defaultdict(list); by_sid_cohorts: dict[str,list[dict[str,Any]]]=defaultdict(list)
    for a in agents:
        if a.get("alive",True): by_sid_agents[str(a.get("species_id"))].append(a)
    for c in cohorts:
        if float(c.get("count",0))>0: by_sid_cohorts[str(c.get("species_id"))].append(c)
    for sp in species:
        sid=str(sp.get("id")); pop=float(pops.get(sid,0)); sp["last_births"]=round(float(births.get(sid,0)),3); sp["last_deaths"]=round(float(deaths.get(sid,0)),3)
        sp["population"]=round(pop,3); sp["current_generation"]=int(world.get("generation",0))
        if pop<=0.03 and sp.get("extinct_generation") is None:
            sp["last_range"]=copy.deepcopy(sp.get("range",[])); sp["range"]=[]; sp["population"]=0.0; sp["extinct_generation"]=int(world.get("generation",0))
            cause_counter=causes.get(sid,Counter()); sp["extinction_cause"]=(cause_counter.most_common(1)[0][0] if cause_counter else "demographic collapse")
            continue
        if pop<=0: continue
        scells=cells.get(sid,set()); sp["range"]=[[x,y] for x,y in sorted(scells,key=lambda c:(c[1],c[0]))]
        if scells:
            cx=mean(x for x,_ in scells); cy=mean(y for _,y in scells); sp["x"]=round((cx+.5)*160/GRID_COLS,3); sp["y"]=round((cy+.5)*100/GRID_ROWS,3)
            seen=set(sp.get("regions_seen",[])); seen.update(region_name(c) for c in scells); sp["regions_seen"]=sorted(seen)
        contributors: list[tuple[dict[str,float],float]]=[]
        for a in by_sid_agents[sid]: contributors.append((a.get("genes",{}),1.0))
        for c in by_sid_cohorts[sid]: contributors.append((c.get("genes",{}),float(c.get("count",0))))
        weight=sum(w for _,w in contributors) or 1.0
        newgenome={}
        for locus in GENE_LOCI:
            lo,hi=TRAIT_BOUNDS.get(locus,(0,1)); newgenome[locus]=round(clamp(sum(float(g.get(locus,_base_gene(sp,locus)))*w for g,w in contributors)/weight,lo,hi),6)
        sp["genome"].update(newgenome)
        # Genetic diversity is now measured from actual population state rather than
        # incremented as a species-level random walk.
        variances=[]
        for locus in ("temp_pref","moisture_pref","mobility","body_size","immune","speed","complexity","sociality"):
            m=newgenome[locus]; lo,hi=TRAIT_BOUNDS[locus]; width=max(1e-9,hi-lo)
            var=sum(((float(g.get(locus,m))-m)/width)**2*w for g,w in contributors)/weight
            variances.append(var)
        div=clamp(math.sqrt(mean(variances))*3.2,0.015,0.95)
        sp["genetic_diversity"]=round(div,5); sp["heterozygosity"]=round(clamp(div*.92+0.02,0.01,.98),5); sp["inbreeding"]=round(clamp((.14-div)*.8 if div<.14 else float(sp.get("inbreeding",0))*.96,0,.85),5)
        sp["peak_population"]=round(max(float(sp.get("peak_population",0)),pop),3); sp["peak_range"]=max(int(sp.get("peak_range",0)),len(scells))
        # Keep legacy trait mirrors synchronized for renderers and older layers.
        for key in ("temp_pref","moisture_pref","tolerance","mobility","fecundity","body_size"):
            sp.setdefault("traits",{})[key]=round(float(newgenome[key]),5)


def _derive_interactions(species: list[dict[str, Any]], kill_stats: dict[tuple[str,str],float], competition_stats: dict[tuple[str,str],float]) -> list[dict[str, Any]]:
    rows=[]
    pops={str(s.get("id")):max(1,float(s.get("population",0))) for s in species}
    for (pred,prey),kills in kill_stats.items():
        if kills<=0: continue
        rows.append({"type":"predation","source":pred,"target":prey,"strength":round(clamp(kills/max(1,pops.get(prey,1))*.8,0.001,1),5),"observed_kills":round(kills,3)})
    for (a,b),score in competition_stats.items():
        if score<=0: continue
        rows.append({"type":"competition","source":a,"target":b,"strength":round(clamp(score*.08,0.001,1),5)})
    return rows


def _connected_components(cells: set[tuple[int,int]]) -> list[set[tuple[int,int]]]:
    unseen=set(cells); comps=[]
    while unseen:
        start=min(unseen); unseen.remove(start); comp={start}; stack=[start]
        while stack:
            cur=stack.pop()
            for n in neighbors(cur):
                if n in unseen: unseen.remove(n); comp.add(n); stack.append(n)
        comps.append(comp)
    return sorted(comps,key=len,reverse=True)


def _component_genome(sid: str, comp: set[tuple[int,int]], agents: list[dict[str,Any]], cohorts: list[dict[str,Any]], fallback: dict[str,float]) -> tuple[dict[str,float],float]:
    contrib=[]
    for a in agents:
        if a.get("alive",True) and str(a.get("species_id"))==sid and _parse_cell(a.get("cell",[0,0])) in comp: contrib.append((a.get("genes",{}),1.0))
    for c in cohorts:
        if str(c.get("species_id"))==sid and float(c.get("count",0))>0 and _parse_cell(c.get("cell",[0,0])) in comp: contrib.append((c.get("genes",{}),float(c.get("count",0))))
    total=sum(w for _,w in contrib)
    if total<=0:return dict(fallback),0
    out={l:sum(float(g.get(l,fallback.get(l,0)))*w for g,w in contrib)/total for l in GENE_LOCI}
    return out,total


def _genetic_distance(a: dict[str,float], b: dict[str,float]) -> float:
    vals=[]
    for locus in ("temp_pref","moisture_pref","tolerance","mobility","body_size","immune","speed","sensory","complexity","aquatic"):
        lo,hi=TRAIT_BOUNDS[locus]; vals.append(abs(float(a.get(locus,0))-float(b.get(locus,0)))/max(1e-9,hi-lo))
    return mean(vals)


def _new_species_name(world: dict[str,Any], species: list[dict[str,Any]], rng: random.Random) -> str:
    used={str(s.get("name")) for s in species}
    for _ in range(100):
        name=f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
        if name not in used:return name
    return f"divergent lineage {int(world.get('next_species_id',1))}"


def _maybe_speciate(world: dict[str,Any], state: dict[str,Any], species: list[dict[str,Any]], agents: list[dict[str,Any]], cohorts: list[dict[str,Any]], rng: random.Random) -> list[dict[str,Any]]:
    events=[]; new_species=[]
    for sp in list(_living(species)):
        sid=str(sp.get("id")); cells={_parse_cell(c.get("cell",[0,0])) for c in cohorts if str(c.get("species_id"))==sid and float(c.get("count",0))>1}
        cells.update(_parse_cell(a.get("cell",[0,0])) for a in agents if a.get("alive",True) and str(a.get("species_id"))==sid)
        comps=_connected_components(cells)
        if len(comps)<2: continue
        base=sp.get("genome",{})
        second=comps[1]; cg,count=_component_genome(sid,second,agents,cohorts,base)
        if count<max(35.0,float(sp.get("population",0))*.12): continue
        key=f"{sid}:{','.join(sorted(_cell_key(c) for c in second)[:8])}"; iso=state.setdefault("isolation",{}); iso[key]=round(float(iso.get(key,0))+float(state.get("checkpoint_days",DEFAULT_CHECKPOINT_DAYS)),3)
        dist=_genetic_distance(cg,base)
        # Classification happens only after sustained isolation and measurable divergence.
        if iso[key] < 8*YEAR_DAYS or dist < 0.065: continue
        n=int(world.get("next_species_id",1)); world["next_species_id"]=n+1; nid=f"sp-{n:05d}"; child=copy.deepcopy(sp); child["id"]=nid; child["name"]=_new_species_name(world,species+new_species,rng); child["parent_id"]=sid; child["born_generation"]=int(world.get("generation",0)); child["origin_generation"]=int(world.get("generation",0)); child["offspring_lineages"]=[]; child["extinct_generation"]=None; child["extinction_cause"]=None; child["peak_population"]=0.0; child["peak_range"]=0; child["socius"]=copy.deepcopy(sp.get("socius",{})); child.get("socius",{}).update({"group_ids":[],"experience_generations":0}); child["genome"]={k:round(float(v),6) for k,v in cg.items()}
        for a in agents:
            if a.get("alive",True) and str(a.get("species_id"))==sid and _parse_cell(a.get("cell",[0,0])) in second: a["species_id"]=nid
        for c in cohorts:
            if str(c.get("species_id"))==sid and _parse_cell(c.get("cell",[0,0])) in second: c["species_id"]=nid; c["isolation_days"]=0
        sp.setdefault("offspring_lineages",[]).append(nid); new_species.append(child); iso.pop(key,None)
        events.append(_event(world,"speciation",nid,f"{child['name']} is recognized as reproductively isolated from {sp.get('name')}.",parent=sid,genetic_distance=round(dist,5),isolated_days=8*YEAR_DAYS))
    species.extend(new_species)
    return events


def _sync_world_metadata(world: dict[str,Any], state: dict[str,Any], agents: list[dict[str,Any]], cohorts: list[dict[str,Any]]) -> None:
    living_agents=sum(1 for a in agents if a.get("alive",True)); cohort_count=sum(1 for c in cohorts if float(c.get("count",0))>.03)
    state["statistics"].update({"explicit_organisms":living_agents,"cohorts":cohort_count,"sim_year":round(float(state.get("sim_day",0))/float(state.get("year_days",YEAR_DAYS)),5)})
    state["observation_index"]=int(world.get("generation",0))
    world["engine"]="VIVARIUM"; world["vivarium"]={"schema":VIVARIUM_SCHEMA_VERSION,"sim_day":round(float(state.get("sim_day",0)),3),"sim_year":round(float(state.get("sim_day",0))/float(state.get("year_days",YEAR_DAYS)),4),"checkpoint_days":int(state.get("checkpoint_days",DEFAULT_CHECKPOINT_DAYS)),"observation_index":int(state.get("observation_index",0)),"explicit_organisms":living_agents,"cohorts":cohort_count,"last_checkpoint":copy.deepcopy(state.get("last_checkpoint",{}))}
    clocks=world.setdefault("clocks",{}); clocks["ecology_days"]=round(float(state.get("sim_day",0)),3); clocks["evolution_years"]=round(float(state.get("sim_day",0))/YEAR_DAYS,5)


def advance_vivarium(world: dict[str,Any], species: list[dict[str,Any]], env: dict[str,Any], pathogens: list[dict[str,Any]], plates: dict[str,Any], interactions: list[dict[str,Any]], rng: random.Random) -> tuple[list[dict[str,Any]], list[dict[str,Any]]]:
    state,agents,cohorts,eco=ensure_vivarium_state(world,species,env,plates,save=False)
    days=int(clamp(int(state.get("checkpoint_days",DEFAULT_CHECKPOINT_DAYS)),1,60)); pop_before=sum(float(s.get("population",0)) for s in _living(species))
    active_cells={_parse_cell(a.get("cell",[0,0])) for a in agents if a.get("alive",True)}|{_parse_cell(c.get("cell",[0,0])) for c in cohorts if float(c.get("count",0))>0}
    if not active_cells: active_cells={(GRID_COLS//2,GRID_ROWS//2)}
    _recalibrate_active_cells(world,env,plates,eco,active_cells)
    births: defaultdict[str,float]=defaultdict(float); deaths: defaultdict[str,float]=defaultdict(float); causes: dict[str,Counter]=defaultdict(Counter); birth_records=[]; death_records=[]; kill_stats: defaultdict[tuple[str,str],float]=defaultdict(float); competition_stats: defaultdict[tuple[str,str],float]=defaultdict(float)
    species_by_id={str(s.get("id")):s for s in _living(species)}; world["_vivarium_pathogens"]=pathogens; world["_vivarium_new_pathogens"]=[]
    extreme_days=0
    for _ in range(days):
        state["sim_day"]=round(float(state.get("sim_day",0))+1.0,3); weather=_update_weather(eco,rng); weather["sim_day"]=float(state["sim_day"])
        active_cells={_parse_cell(a.get("cell",[0,0])) for a in agents if a.get("alive",True)}|{_parse_cell(c.get("cell",[0,0])) for c in cohorts if float(c.get("count",0))>0}
        _update_biotic_engineering(agents,cohorts,eco,active_cells)
        _grow_ecosystem(eco,active_cells,weather)
        _cohort_daily_step(world,state,cohorts,species_by_id,eco,weather,rng,births,deaths,causes,competition_stats)
        _cohort_predation(cohorts,species_by_id,eco,rng,deaths,causes,kill_stats)
        _agent_daily_step(world,state,agents,cohorts,species_by_id,eco,weather,rng,births,deaths,causes,birth_records,death_records,kill_stats)
        _pathogen_daily(world,state,species,pathogens,agents,cohorts,rng,deaths,causes)
        if weather["storm"]>.55 or abs(weather["temperature_anomaly"])>.13: extreme_days+=1
        cohorts=_merge_and_bound_cohorts(cohorts)
        # Dead explicit organisms move to fossil records; keeping only a bounded recent
        # sample avoids turning organisms.json into an unbounded graveyard.
        recent_dead=[a for a in agents if not a.get("alive",True)][-120:]; agents=[a for a in agents if a.get("alive",True)]+recent_dead
    _rebalance_explicit_resolution(world,state,species,agents,cohorts,eco,rng)
    _update_pathogen_summary(species,pathogens,agents,cohorts)
    _sync_species_from_population(world,species,agents,cohorts,births,deaths,causes)
    # Event helpers read the public VIVARIUM clock. Publish the new simulated day
    # before classification/disease events are constructed so their timestamps
    # describe when they happened rather than the previous observation.
    world.setdefault("vivarium", {})["sim_day"] = round(float(state.get("sim_day", 0)), 3)
    events=_maybe_speciate(world,state,species,agents,cohorts,rng)
    if events:
        _sync_species_from_population(world,species,agents,cohorts,births,deaths,causes)
    interactions=_derive_interactions(species,kill_stats,competition_stats)
    pop_after=sum(float(s.get("population",0)) for s in _living(species)); total_births=sum(births.values()); total_deaths=sum(deaths.values()); all_causes=Counter(); [all_causes.update(v) for v in causes.values()]
    state["last_checkpoint"]={"observation_index":int(world.get("generation",0)),"sim_day_start":round(float(state.get("sim_day",0))-days,3),"sim_day_end":round(float(state.get("sim_day",0)),3),"simulated_days":days,"population_before":round(pop_before,3),"population_after":round(pop_after,3),"births":round(total_births,3),"deaths":round(total_deaths,3),"death_causes":{k:round(v,3) for k,v in all_causes.most_common()},"extreme_weather_days":extreme_days,"observed_predation":round(sum(kill_stats.values()),3)}
    if pop_before>0 and pop_after < pop_before*.55:
        events.append(_event(world,"mass_extinction","world",f"The biosphere loses {(1-pop_after/pop_before)*100:.1f}% of its organisms during one VIVARIUM observation interval.",population_before=round(pop_before,2),population_after=round(pop_after,2)))
    for sp in species:
        sid=str(sp.get("id"));
        if float(deaths.get(sid,0))>=max(8,float(sp.get("population",0))*.12):
            top=causes[sid].most_common(1)[0][0] if causes[sid] else "mortality"
            events.append(_event(world,"observation",sid,f"{sp.get('name')} loses {deaths[sid]:.0f} organisms, primarily to {top}."))
    for p in world.pop("_vivarium_new_pathogens",[]):
        host=next(iter(p.get("hosts",{})),"world"); name=p.get("name","A pathogen"); hsp=next((s for s in species if str(s.get("id"))==host),None)
        events.append(_event(world,"disease",str(p.get("id")),f"{name} emerges in {hsp.get('name') if hsp else host}.",host=host))
    world.pop("_vivarium_pathogens",None)
    active_cells={_parse_cell(a.get("cell",[0,0])) for a in agents if a.get("alive",True)}|{_parse_cell(c.get("cell",[0,0])) for c in cohorts if float(c.get("count",0))>0}
    _publish_biotic_modifiers(env,eco,active_cells)
    _sync_world_metadata(world,state,agents,cohorts)
    save_vivarium_state(state,agents,cohorts,eco)
    if birth_records:
        from .storage import append_ndjson
        append_ndjson(BIRTHS_PATH,birth_records[-500:])
    if death_records:
        from .storage import append_ndjson
        append_ndjson(DEATHS_PATH,death_records[-500:])
    return interactions,events


def validate_vivarium_state(world: dict[str,Any], species: list[dict[str,Any]]) -> list[str]:
    errors=[]; state,agents,cohorts,eco=load_vivarium_state()
    if int(state.get("schema",0))!=VIVARIUM_SCHEMA_VERSION: return ["missing or invalid VIVARIUM state"]
    if not isinstance(eco.get("cells"),dict) or len(eco.get("cells",{}))<GRID_COLS*GRID_ROWS*.80: errors.append("VIVARIUM ecosystem grid incomplete")
    ids=[str(a.get("id")) for a in agents];
    if len(ids)!=len(set(ids)): errors.append("duplicate VIVARIUM organism ids")
    valid_species={str(s.get("id")) for s in species}
    for a in agents:
        if str(a.get("species_id")) not in valid_species: errors.append(f"orphan organism {a.get('id')}")
        x,y=_parse_cell(a.get("cell",[0,0]));
        if not (0<=x<GRID_COLS and 0<=y<GRID_ROWS): errors.append(f"organism outside world {a.get('id')}")
        if not 0<=float(a.get("energy",0))<=1.001 or not 0<=float(a.get("health",0))<=1.001: errors.append(f"invalid organism condition {a.get('id')}")
    for c in cohorts:
        if str(c.get("species_id")) not in valid_species: errors.append(f"orphan cohort {c.get('id')}")
        if float(c.get("count",0))<0: errors.append(f"negative cohort {c.get('id')}")
    pops,_=_population_rows(species,agents,cohorts)
    for sp in species:
        sid=str(sp.get("id")); expected=float(pops.get(sid,0)); actual=float(sp.get("population",0))
        if sp.get("extinct_generation") is None and abs(expected-actual)>max(.12,expected*.002): errors.append(f"VIVARIUM population mismatch {sid}: {expected:.3f} != {actual:.3f}")
    if float(state.get("sim_day",0))<0: errors.append("negative simulated time")
    return errors


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def vivarium_summary(world: dict[str,Any], species: list[dict[str,Any]]) -> dict[str,Any]:
    state,agents,cohorts,eco=load_vivarium_state(); last=state.get("last_checkpoint",{})
    living_agents=[a for a in agents if a.get("alive",True)]
    return {"engine":"VIVARIUM","schema":state.get("schema"),"observation_index":world.get("generation"),"sim_day":state.get("sim_day"),"sim_year":round(float(state.get("sim_day",0))/float(state.get("year_days",YEAR_DAYS)),4),"explicit_organisms":len(living_agents),"cohorts":len([c for c in cohorts if float(c.get("count",0))>0]),"conceptual_population":round(sum(float(s.get("population",0)) for s in _living(species)),2),"last_checkpoint":last,"tracked_birth_records":_line_count(BIRTHS_PATH),"tracked_death_records":_line_count(DEATHS_PATH)}
