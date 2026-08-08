from __future__ import annotations

import hashlib
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD_PATH = ROOT / "world" / "current.json"
SPECIES_PATH = ROOT / "world" / "species.json"
ENV_PATH = ROOT / "world" / "environment.json"
EVENTS_PATH = ROOT / "fossils" / "events.ndjson"
RENDER_PATH = ROOT / "renders" / "current.svg"
README_PATH = ROOT / "README.md"

README_START = "<!-- PHYLUM:STATE:START -->"
README_END = "<!-- PHYLUM:STATE:END -->"

ADJECTIVES = [
    "ashen", "brine", "cinder", "glass", "hollow", "ivory", "mire", "pale",
    "rust", "sable", "silt", "still", "thorn", "velvet", "wither", "wound",
]
NOUNS = [
    "branch", "choir", "crawler", "fan", "filament", "gill", "lace", "mote",
    "petal", "reed", "ribbon", "spine", "veil", "worm", "frond", "bell",
]


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
    return clamp(temp, 0, 1), clamp(moisture, 0, 1), clamp(resources, 0.05, 1.2)


def suitability(sp: dict[str, Any], local: tuple[float, float, float]) -> float:
    t, m, resources = local
    td = abs(t - sp["traits"]["temp_pref"])
    md = abs(m - sp["traits"]["moisture_pref"])
    tolerance = sp["traits"]["tolerance"]
    fit = max(0.0, 1.0 - (td + md) / max(tolerance * 2.0, 0.05))
    return clamp((fit * 0.72) + (min(resources, 1.0) * 0.28), 0, 1)


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


def evolve_one(lineage: str | None = None) -> dict[str, Any]:
    world, species, env = load_state()
    next_gen = int(world["generation"]) + 1
    lineage = lineage or os.getenv("GITHUB_REPOSITORY") or world.get("active_lineage") or "origin"
    rng = deterministic_rng(int(world["seed"]), next_gen, lineage)
    events: list[dict[str, Any]] = []

    # Slow climate drift.
    env["temperature"] = round(clamp(env["temperature"] + rng.gauss(0, 0.006), 0.10, 0.90), 4)
    env["moisture"] = round(clamp(env["moisture"] + rng.gauss(0, 0.008), 0.08, 0.92), 4)
    env["resources"] = round(clamp(env["resources"] + rng.gauss(0, 0.010), 0.35, 1.00), 4)

    # Rare global environmental shocks.
    shock_roll = rng.random()
    if shock_roll < 0.012:
        env["moisture"] = round(clamp(env["moisture"] - rng.uniform(0.08, 0.18), 0.05, 0.95), 4)
        events.append(event(next_gen, "climate", "drought", "A prolonged dry phase begins."))
    elif shock_roll < 0.020:
        env["temperature"] = round(clamp(env["temperature"] - rng.uniform(0.07, 0.14), 0.05, 0.95), 4)
        events.append(event(next_gen, "climate", "cooling", "A rapid cooling phase alters the habitat."))
    elif shock_roll < 0.030:
        env["resources"] = round(clamp(env["resources"] + rng.uniform(0.08, 0.18), 0.35, 1.0), 4)
        events.append(event(next_gen, "climate", "bloom", "Resource abundance rises across the world."))

    alive = [s for s in species if s.get("extinct_generation") is None]
    used_names = {s["name"] for s in species}
    newborns: list[dict[str, Any]] = []

    for sp in alive:
        # Move toward one of several sampled nearby cells with higher suitability.
        best_x, best_y = sp["x"], sp["y"]
        best_fit = suitability(sp, env_at(env, best_x, best_y, world["seed"]))
        radius = max(1.0, sp["traits"]["mobility"] * 7.0)
        for _ in range(5):
            tx = clamp(sp["x"] + rng.gauss(0, radius), 0, env["width"] - 1)
            ty = clamp(sp["y"] + rng.gauss(0, radius), 0, env["height"] - 1)
            fit = suitability(sp, env_at(env, tx, ty, world["seed"]))
            if fit > best_fit:
                best_x, best_y, best_fit = tx, ty, fit
        sp["x"] = round(best_x, 3)
        sp["y"] = round(best_y, 3)

        local = env_at(env, sp["x"], sp["y"], world["seed"])
        fit = suitability(sp, local)
        body_cost = 0.015 * sp["traits"]["body_size"]
        growth = (fit - 0.47 - body_cost) * sp["traits"]["fecundity"]
        noise = rng.gauss(0, 0.035)
        next_pop = max(0.0, sp["population"] * (1.0 + growth + noise))

        # Soft local carrying capacity.
        carrying = 1800.0 * local[2] / max(0.35, sp["traits"]["body_size"] ** 0.45)
        if next_pop > carrying:
            next_pop = carrying + (next_pop - carrying) * 0.15
        sp["population"] = round(next_pop, 2)
        sp["last_fitness"] = round(fit, 4)

        if sp["population"] < 2.0:
            sp["population"] = 0.0
            sp["extinct_generation"] = next_gen
            events.append(event(next_gen, "extinction", sp["id"], f"{sp['name']} becomes extinct."))
            continue

        # Speciation: more likely in large, long-lived populations and under middling fitness.
        age = next_gen - sp["born_generation"]
        speciation_p = 0.0025
        speciation_p += min(0.010, sp["population"] / 350000.0)
        speciation_p += min(0.004, age / 20000.0)
        if age >= 8 and sp["population"] >= 80 and rng.random() < speciation_p:
            child_id = f"sp-{world['next_species_id']:05d}"
            world["next_species_id"] += 1
            child_pop = max(12.0, sp["population"] * rng.uniform(0.08, 0.20))
            sp["population"] = round(max(2.0, sp["population"] - child_pop), 2)
            child_name = generated_name(rng, used_names)
            used_names.add(child_name)
            child = {
                "id": child_id,
                "name": child_name,
                "parent_id": sp["id"],
                "born_generation": next_gen,
                "extinct_generation": None,
                "population": round(child_pop, 2),
                "x": round(clamp(sp["x"] + rng.gauss(0, 1.8), 0, env["width"] - 1), 3),
                "y": round(clamp(sp["y"] + rng.gauss(0, 1.8), 0, env["height"] - 1), 3),
                "traits": mutate_traits(sp, rng),
                "last_fitness": sp["last_fitness"],
            }
            newborns.append(child)
            events.append(event(next_gen, "speciation", child_id, f"{child_name} diverges from {sp['name']}."))

    species.extend(newborns)

    living = [s for s in species if s.get("extinct_generation") is None]
    total_pop = round(sum(s["population"] for s in living), 2)
    world["generation"] = next_gen
    world["active_lineage"] = lineage
    world["last_evolved_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    world["living_species"] = len(living)
    world["extinct_species"] = len(species) - len(living)
    world["total_population"] = total_pop

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
    update_readme(world, species, env, events)
    return {"world": world, "species": species, "environment": env, "events": events}


def event(generation: int, kind: str, subject: str, text: str) -> dict[str, Any]:
    return {"generation": generation, "kind": kind, "subject": subject, "text": text}


def append_events(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, sort_keys=True) + "\n")


def _biome_color(temp: float, moisture: float, resources: float) -> str:
    # Intentionally restrained earth/ink palette.
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


def render_svg(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any]) -> None:
    width_px, height_px = 960, 600
    cols, rows = 48, 30
    cw, ch = width_px / cols, height_px / rows
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_px} {height_px}" role="img" aria-label="PHYLUM generation {world["generation"]}">',
        '<rect width="100%" height="100%" fill="#11110f"/>',
    ]
    for gy in range(rows):
        for gx in range(cols):
            x = gx * (env["width"] - 1) / (cols - 1)
            y = gy * (env["height"] - 1) / (rows - 1)
            t, m, r = env_at(env, x, y, world["seed"])
            c = _biome_color(t, m, r)
            parts.append(f'<rect x="{gx*cw:.2f}" y="{gy*ch:.2f}" width="{cw+0.4:.2f}" height="{ch+0.4:.2f}" fill="{c}"/>')

    # Subtle contour-like lines.
    for i in range(1, 10):
        y = i * height_px / 10
        parts.append(f'<path d="M 0 {y:.1f} C 220 {y-24:.1f}, 420 {y+26:.1f}, 620 {y-10:.1f} S 840 {y+20:.1f}, 960 {y:.1f}" fill="none" stroke="#11110f" stroke-opacity="0.12" stroke-width="1"/>')

    living = [s for s in species if s.get("extinct_generation") is None and s["population"] > 0]
    max_pop = max((s["population"] for s in living), default=1.0)
    for sp in living:
        px = sp["x"] / (env["width"] - 1) * width_px
        py = sp["y"] / (env["height"] - 1) * height_px
        radius = 4.0 + 17.0 * math.sqrt(sp["population"] / max_pop)
        # Stable hue from species id without importing color libraries.
        h = int(hashlib.sha1(sp["id"].encode()).hexdigest()[:6], 16)
        hue = h % 360
        parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{radius:.2f}" fill="hsl({hue} 46% 72%)" fill-opacity="0.82" stroke="#11110f" stroke-width="1.5"><title>{sp["name"]}: {int(sp["population"])} organisms</title></circle>')
        if sp["population"] == max_pop or len(living) <= 6:
            label = sp["name"].replace("&", "&amp;").replace("<", "&lt;")
            parts.append(f'<text x="{px+radius+5:.2f}" y="{py+4:.2f}" font-family="ui-monospace, monospace" font-size="11" fill="#f1efe7" stroke="#11110f" stroke-width="2.5" paint-order="stroke">{label}</text>')

    parts.append('<rect x="16" y="16" width="260" height="70" rx="3" fill="#11110f" fill-opacity="0.82"/>')
    parts.append(f'<text x="30" y="45" font-family="ui-monospace, monospace" font-size="20" fill="#f1efe7">PHYLUM / GEN {world["generation"]:06d}</text>')
    parts.append(f'<text x="30" y="68" font-family="ui-monospace, monospace" font-size="12" fill="#c9c5b8">{len(living)} living lineages · {int(world["total_population"])} organisms</text>')
    parts.append('</svg>')
    RENDER_PATH.parent.mkdir(parents=True, exist_ok=True)
    RENDER_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")


def update_readme(world: dict[str, Any], species: list[dict[str, Any]], env: dict[str, Any], events: list[dict[str, Any]]) -> None:
    if not README_PATH.exists():
        return
    text = README_PATH.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return
    living = [s for s in species if s.get("extinct_generation") is None]
    dominant = max(living, key=lambda s: s["population"], default=None)
    last_event = events[-1]["text"] if events else latest_event_text()
    block = [
        README_START,
        f"**Generation:** `{world['generation']:,}`  ",
        f"**Living lineages:** `{len(living)}`  ",
        f"**Extinct lineages:** `{world['extinct_species']}`  ",
        f"**Population:** `{int(world['total_population']):,}`  ",
        f"**Dominant lineage:** `{dominant['name'] if dominant else 'none'}`  ",
        f"**Latest fossil:** {last_event or 'No major event recorded yet.'}",
        README_END,
    ]
    before, rest = text.split(README_START, 1)
    _, after = rest.split(README_END, 1)
    README_PATH.write_text(before + "\n".join(block) + after, encoding="utf-8")


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


def commit_message() -> str:
    world, _, _ = load_state()
    fossil = latest_event()
    if fossil and fossil.get("generation") == world["generation"]:
        # Keep commit summaries compact.
        summary = str(fossil.get("text", "world advances")).rstrip(".")
        return f"gen {world['generation']:06d} — {summary[:68]}"
    return f"gen {world['generation']:06d} — biosphere advances"
