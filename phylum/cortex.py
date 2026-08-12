from __future__ import annotations

"""CORTEX — bounded evolving neural controllers for VIVARIUM organisms.

CORTEX deliberately does not call an LLM during canonical evolution.  The canonical
world must remain deterministic and runnable inside GitHub Actions.  Resolved
organisms receive tiny inherited neural controllers; lifetime reward-modulated
plasticity changes only a non-heritable plastic layer.  An optional OpenAI-compatible
*local* LLM bridge is provided for manual experiments/probes and is never invoked by
normal evolution.
"""

import json
import math
import os
import random
import urllib.error
import urllib.request
from typing import Any

from .utils import clamp, stable_int

CORTEX_SCHEMA_VERSION = 1
INPUT_NAMES = (
    "energy",
    "health",
    "food",
    "climate_fit",
    "threat",
    "social_opportunity",
    "mate_opportunity",
    "infection",
    "maturity",
    "novelty",
)
ACTION_NAMES = ("rest", "forage", "explore", "avoid", "socialize", "mate")
MAX_HIDDEN = 8
MIN_HIDDEN = 3
MAX_PLASTIC = 0.75
MAX_WEIGHT = 2.5


def _neural_complexity(species: dict[str, Any], genes: dict[str, Any]) -> float:
    nerve = species.get("nerve", {}) if isinstance(species, dict) else {}
    arch = nerve.get("architecture", {}) if isinstance(nerve, dict) else {}
    inherited = clamp(float(genes.get("complexity", 0.05)), 0, 1)
    nerve_score = clamp(float(arch.get("neural_complexity", inherited)), 0, 1)
    sensory = clamp(float(genes.get("sensory", 0.05)), 0, 1)
    return clamp(nerve_score * 0.62 + inherited * 0.25 + sensory * 0.13, 0, 1)


def _plasticity(species: dict[str, Any], genes: dict[str, Any]) -> float:
    nerve = species.get("nerve", {}) if isinstance(species, dict) else {}
    arch = nerve.get("architecture", {}) if isinstance(nerve, dict) else {}
    learning = clamp(float(arch.get("learning_rate", 0.04)), 0, 1)
    complexity = _neural_complexity(species, genes)
    return clamp(0.015 + learning * 0.55 + complexity * 0.18, 0.01, 0.58)


def _gate(species: dict[str, Any], genes: dict[str, Any]) -> float:
    # Primitive organisms retain mostly reflexive priors; increasingly complex
    # nervous systems give the evolved controller more authority over behavior.
    n = _neural_complexity(species, genes)
    return clamp(0.04 + n ** 1.35 * 0.86, 0.04, 0.90)


def _hidden_count(species: dict[str, Any], genes: dict[str, Any]) -> int:
    return int(clamp(round(MIN_HIDDEN + _neural_complexity(species, genes) * (MAX_HIDDEN - MIN_HIDDEN)), MIN_HIDDEN, MAX_HIDDEN))


def _zeros_matrix(rows: int, cols: int) -> list[list[float]]:
    return [[0.0 for _ in range(cols)] for _ in range(rows)]


def _new_genome(seed: int, species: dict[str, Any], genes: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(seed)
    hidden = _hidden_count(species, genes)
    complexity = _neural_complexity(species, genes)
    scale = 0.12 + complexity * 0.16
    w1 = [[round(rng.gauss(0.0, scale), 6) for _ in INPUT_NAMES] for _ in range(MAX_HIDDEN)]
    b1 = [round(rng.gauss(0.0, scale * 0.35), 6) for _ in range(MAX_HIDDEN)]
    w2 = [[round(rng.gauss(0.0, scale), 6) for _ in range(MAX_HIDDEN)] for _ in ACTION_NAMES]
    b2 = [round(rng.gauss(0.0, scale * 0.30), 6) for _ in ACTION_NAMES]
    return {
        "hidden": hidden,
        "w1": w1,
        "b1": b1,
        "w2": w2,
        "b2": b2,
        "mutation_rate": round(clamp(0.010 + float(genes.get("recombination", 0.4)) * 0.022, 0.006, 0.045), 6),
    }


def create_brain(world_seed: int, organism_id: str, species: dict[str, Any], genes: dict[str, Any], origin: str = "founder") -> dict[str, Any]:
    seed = stable_int(f"cortex:{CORTEX_SCHEMA_VERSION}:{world_seed}:{organism_id}:{species.get('id')}:{origin}")
    genome = _new_genome(seed, species, genes)
    return {
        "schema": CORTEX_SCHEMA_VERSION,
        "kind": "tiny-neural-controller",
        "origin": origin,
        "gate": round(_gate(species, genes), 6),
        "plasticity": round(_plasticity(species, genes), 6),
        "genome": genome,
        "plastic": {
            "w2": _zeros_matrix(len(ACTION_NAMES), MAX_HIDDEN),
            "b2": [0.0 for _ in ACTION_NAMES],
        },
        "state": {
            "decisions": 0,
            "reward_ema": 0.0,
            "last_reward": 0.0,
            "last_action": "rest",
            "last_confidence": 0.0,
            "last_hidden": [0.0 for _ in range(MAX_HIDDEN)],
        },
    }


def ensure_agent_brain(agent: dict[str, Any], species: dict[str, Any], world_seed: int) -> dict[str, Any]:
    brain = agent.get("brain")
    if not isinstance(brain, dict) or int(brain.get("schema", 0)) != CORTEX_SCHEMA_VERSION:
        brain = create_brain(world_seed, str(agent.get("id", "unknown")), species, agent.get("genes", {}), str(agent.get("origin", "migration")))
        agent["brain"] = brain
    # Refresh only phenotype-like gate/plasticity.  The inherited genome is not
    # rewritten when species averages later change.
    brain["gate"] = round(_gate(species, agent.get("genes", {})), 6)
    brain["plasticity"] = round(_plasticity(species, agent.get("genes", {})), 6)
    brain.setdefault("plastic", {"w2": _zeros_matrix(len(ACTION_NAMES), MAX_HIDDEN), "b2": [0.0 for _ in ACTION_NAMES]})
    brain.setdefault("state", {"decisions": 0, "reward_ema": 0.0, "last_reward": 0.0, "last_action": "rest", "last_confidence": 0.0, "last_hidden": [0.0 for _ in range(MAX_HIDDEN)]})
    return brain


def ensure_cohort_cortex(cohort: dict[str, Any], species: dict[str, Any], world_seed: int) -> dict[str, Any]:
    # Cohorts are deliberately compressed: store a bounded neural phenotype, not
    # hundreds of neural weights for organisms that are not currently resolved.
    genes = cohort.get("genes", {})
    row = cohort.get("cortex")
    if not isinstance(row, dict) or int(row.get("schema", 0)) != CORTEX_SCHEMA_VERSION:
        row = {
            "schema": CORTEX_SCHEMA_VERSION,
            "controller_seed": stable_int(f"cortex-cohort:{world_seed}:{cohort.get('id')}:{species.get('id')}") & 0xFFFFFFFF,
            "neural_complexity": round(_neural_complexity(species, genes), 6),
            "plasticity": round(_plasticity(species, genes), 6),
            "hidden": _hidden_count(species, genes),
        }
        cohort["cortex"] = row
    else:
        row["neural_complexity"] = round(_neural_complexity(species, genes), 6)
        row["plasticity"] = round(_plasticity(species, genes), 6)
        row["hidden"] = _hidden_count(species, genes)
    return row


def _matrix_value(matrix: list[list[float]], r: int, c: int) -> float:
    try:
        return float(matrix[r][c])
    except (IndexError, TypeError, ValueError):
        return 0.0


def _vector_value(vector: list[float], i: int) -> float:
    try:
        return float(vector[i])
    except (IndexError, TypeError, ValueError):
        return 0.0


def _forward(brain: dict[str, Any], inputs: list[float]) -> tuple[list[float], list[float]]:
    genome = brain.get("genome", {})
    plastic = brain.get("plastic", {})
    hidden_n = int(clamp(int(genome.get("hidden", MIN_HIDDEN)), MIN_HIDDEN, MAX_HIDDEN))
    w1 = genome.get("w1", [])
    b1 = genome.get("b1", [])
    hidden = [0.0 for _ in range(MAX_HIDDEN)]
    for h in range(hidden_n):
        z = _vector_value(b1, h)
        for i, value in enumerate(inputs[: len(INPUT_NAMES)]):
            z += _matrix_value(w1, h, i) * float(value)
        hidden[h] = math.tanh(z)
    logits: list[float] = []
    w2 = genome.get("w2", [])
    b2 = genome.get("b2", [])
    pw2 = plastic.get("w2", [])
    pb2 = plastic.get("b2", [])
    for a in range(len(ACTION_NAMES)):
        z = _vector_value(b2, a) + _vector_value(pb2, a)
        for h in range(hidden_n):
            z += (_matrix_value(w2, a, h) + _matrix_value(pw2, a, h)) * hidden[h]
        logits.append(z)
    return hidden, logits


def _threat_score(agent: dict[str, Any]) -> float:
    vals = [float(m.get("score", 0)) for m in agent.get("memory", []) if isinstance(m, dict) and m.get("kind") == "threat"]
    return clamp(max(vals or [0.0]), 0, 1)


def _novelty(agent: dict[str, Any]) -> float:
    memory = [m for m in agent.get("memory", []) if isinstance(m, dict)]
    return clamp(1.0 - len(memory) / 12.0, 0, 1)


def _context(agent: dict[str, Any], species: dict[str, Any], cell_state: dict[str, Any], peers: list[dict[str, Any]]) -> list[float]:
    genes = agent.get("genes", {})
    energy = clamp(float(agent.get("energy", 0.5)), 0, 1)
    health = clamp(float(agent.get("health", 1.0)), 0, 1)
    food = clamp(float(cell_state.get("producer_biomass", 0.0)) / max(1.0, float(cell_state.get("capacity", 1.0))), 0, 1)
    temp_fit = 1.0 - clamp(abs(float(cell_state.get("temperature", 0.5)) - float(genes.get("temp_pref", 0.5))) / max(0.08, float(genes.get("tolerance", 0.25))), 0, 1)
    moist_fit = 1.0 - clamp(abs(float(cell_state.get("moisture", 0.5)) - float(genes.get("moisture_pref", 0.5))) / max(0.08, float(genes.get("tolerance", 0.25))), 0, 1)
    climate_fit = clamp((temp_fit + moist_fit) * 0.5, 0, 1)
    same_species = [p for p in peers if str(p.get("species_id")) == str(agent.get("species_id")) and p.get("id") != agent.get("id") and p.get("alive", True)]
    social_opportunity = clamp(len(same_species) / 6.0, 0, 1)
    mature = 1.0 if str(agent.get("stage")) == "adult" else 0.0
    opposite = any(p.get("stage") == "adult" and p.get("sex") != agent.get("sex") for p in same_species)
    mate_opportunity = 1.0 if mature and opposite else 0.0
    infection = clamp(max([float(v) for v in agent.get("infections", {}).values()] or [0.0]), 0, 1)
    return [energy, health, food, climate_fit, _threat_score(agent), social_opportunity, mate_opportunity, infection, mature, _novelty(agent)]


def _reflex_logits(inputs: list[float]) -> list[float]:
    energy, health, food, climate_fit, threat, social, mate, infection, mature, novelty = inputs
    return [
        (1 - energy) * 0.35 + (1 - health) * 1.35 + infection * 0.45,  # rest
        (1 - energy) * 1.65 + food * 0.62 + health * 0.18,              # forage
        novelty * 0.92 + energy * 0.35 + (1 - food) * 0.28,             # explore
        threat * 1.85 + (1 - climate_fit) * 0.55 + infection * 0.18,    # avoid
        social * 1.10 + health * 0.18 + energy * 0.12,                  # socialize
        mate * 1.35 + mature * 0.30 + energy * 0.34 + health * 0.20,    # mate
    ]


def decide_action(agent: dict[str, Any], species: dict[str, Any], cell_state: dict[str, Any], peers: list[dict[str, Any]], world_seed: int, sim_day: float, rng: random.Random) -> dict[str, Any]:
    brain = ensure_agent_brain(agent, species, world_seed)
    inputs = _context(agent, species, cell_state, peers)
    hidden, neural = _forward(brain, inputs)
    reflex = _reflex_logits(inputs)
    gate = clamp(float(brain.get("gate", 0.05)), 0, 1)
    logits = [(1.0 - gate) * reflex[i] + gate * (neural[i] + reflex[i] * 0.22) for i in range(len(ACTION_NAMES))]
    # Softmax sampling keeps alternative strategies alive.  Advanced controllers
    # are somewhat more decisive while primitive nervous systems remain noisy.
    temperature = 1.15 - gate * 0.45
    peak = max(logits)
    weights = [math.exp(clamp((x - peak) / max(0.25, temperature), -20, 20)) for x in logits]
    total = sum(weights) or 1.0
    draw = rng.random() * total
    idx = 0
    accum = 0.0
    for i, w in enumerate(weights):
        accum += w
        if draw <= accum:
            idx = i
            break
    confidence = weights[idx] / total
    state = brain.setdefault("state", {})
    state["decisions"] = int(state.get("decisions", 0)) + 1
    state["last_action"] = ACTION_NAMES[idx]
    state["last_confidence"] = round(confidence, 6)
    state["last_hidden"] = [round(v, 6) for v in hidden]
    state["last_day"] = round(float(sim_day), 3)
    return {"action": ACTION_NAMES[idx], "confidence": confidence, "gate": gate, "inputs": inputs}


def behavior_modifiers(decision: dict[str, Any]) -> dict[str, float]:
    action = str(decision.get("action", "rest"))
    confidence = clamp(float(decision.get("confidence", 0.0)), 0, 1)
    gate = clamp(float(decision.get("gate", 0.0)), 0, 1)
    strength = confidence * (0.25 + gate * 0.75)
    return {
        "metabolic": 0.88 if action == "rest" else 1.0 + (0.035 * strength if action == "explore" else 0.0),
        "forage": 1.0 + (0.08 * strength if action == "forage" else 0.0),
        "move": 1.0 + (1.45 * strength if action in {"explore", "avoid"} else -0.65 * strength if action == "rest" else 0.0),
        "social": 1.0 + (1.25 * strength if action == "socialize" else 0.0),
        "mate": 1.0 + (0.70 * strength if action == "mate" else 0.0),
        "avoid": 0.16 * strength if action == "avoid" else 0.0,
    }


def brain_energy_cost(agent: dict[str, Any], species: dict[str, Any]) -> float:
    brain = agent.get("brain") or {}
    hidden = int((brain.get("genome") or {}).get("hidden", MIN_HIDDEN))
    gate = clamp(float(brain.get("gate", _gate(species, agent.get("genes", {})))), 0, 1)
    plasticity = clamp(float(brain.get("plasticity", _plasticity(species, agent.get("genes", {})))), 0, 1)
    # Existing NERVE already charges the bulk neural cost.  CORTEX adds only the
    # extra cost of active processing/plasticity so the same brain is not billed twice.
    return 0.00004 + hidden * 0.000012 * gate + plasticity * 0.00011


def learn_from_reward(agent: dict[str, Any], reward: float) -> None:
    brain = agent.get("brain")
    if not isinstance(brain, dict):
        return
    reward = clamp(float(reward), -1.0, 1.0)
    state = brain.setdefault("state", {})
    action = str(state.get("last_action", "rest"))
    try:
        idx = ACTION_NAMES.index(action)
    except ValueError:
        idx = 0
    hidden = [float(x) for x in state.get("last_hidden", [])][:MAX_HIDDEN]
    hidden += [0.0] * (MAX_HIDDEN - len(hidden))
    plastic = brain.setdefault("plastic", {"w2": _zeros_matrix(len(ACTION_NAMES), MAX_HIDDEN), "b2": [0.0 for _ in ACTION_NAMES]})
    w2 = plastic.setdefault("w2", _zeros_matrix(len(ACTION_NAMES), MAX_HIDDEN))
    b2 = plastic.setdefault("b2", [0.0 for _ in ACTION_NAMES])
    lr = clamp(float(brain.get("plasticity", 0.03)), 0.005, 0.6) * 0.055
    # Gentle decay prevents one lucky event from permanently saturating a lifetime policy.
    for a in range(len(ACTION_NAMES)):
        for h in range(MAX_HIDDEN):
            w2[a][h] = round(clamp(float(w2[a][h]) * 0.9995, -MAX_PLASTIC, MAX_PLASTIC), 6)
        b2[a] = round(clamp(float(b2[a]) * 0.9995, -MAX_PLASTIC, MAX_PLASTIC), 6)
    for h in range(MAX_HIDDEN):
        w2[idx][h] = round(clamp(float(w2[idx][h]) + lr * reward * hidden[h], -MAX_PLASTIC, MAX_PLASTIC), 6)
    b2[idx] = round(clamp(float(b2[idx]) + lr * reward * 0.35, -MAX_PLASTIC, MAX_PLASTIC), 6)
    state["last_reward"] = round(reward, 6)
    state["reward_ema"] = round(float(state.get("reward_ema", 0.0)) * 0.96 + reward * 0.04, 6)


def _inherit_value(av: float, bv: float, mutation_rate: float, rng: random.Random) -> float:
    base = av if rng.random() < 0.5 else bv
    if rng.random() < 0.30:
        base = (av + bv) * 0.5
    if rng.random() < mutation_rate:
        base += rng.gauss(0.0, 0.075)
    else:
        base += rng.gauss(0.0, 0.006)
    return round(clamp(base, -MAX_WEIGHT, MAX_WEIGHT), 6)


def inherit_brain(parent_a: dict[str, Any], parent_b: dict[str, Any], child_id: str, world_seed: int, species: dict[str, Any], child_genes: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    a = ensure_agent_brain(parent_a, species, world_seed)
    b = ensure_agent_brain(parent_b, species, world_seed)
    ga, gb = a.get("genome", {}), b.get("genome", {})
    mutation_rate = clamp((float(ga.get("mutation_rate", 0.02)) + float(gb.get("mutation_rate", 0.02))) * 0.5, 0.005, 0.06)
    hidden = int(clamp(round((int(ga.get("hidden", MIN_HIDDEN)) + int(gb.get("hidden", MIN_HIDDEN))) * 0.5), MIN_HIDDEN, MAX_HIDDEN))
    if rng.random() < mutation_rate * 1.4:
        hidden = int(clamp(hidden + (-1 if rng.random() < 0.5 else 1), MIN_HIDDEN, MAX_HIDDEN))
    genome = {
        "hidden": hidden,
        "w1": [[_inherit_value(_matrix_value(ga.get("w1", []), h, i), _matrix_value(gb.get("w1", []), h, i), mutation_rate, rng) for i in range(len(INPUT_NAMES))] for h in range(MAX_HIDDEN)],
        "b1": [_inherit_value(_vector_value(ga.get("b1", []), h), _vector_value(gb.get("b1", []), h), mutation_rate, rng) for h in range(MAX_HIDDEN)],
        "w2": [[_inherit_value(_matrix_value(ga.get("w2", []), aidx, h), _matrix_value(gb.get("w2", []), aidx, h), mutation_rate, rng) for h in range(MAX_HIDDEN)] for aidx in range(len(ACTION_NAMES))],
        "b2": [_inherit_value(_vector_value(ga.get("b2", []), aidx), _vector_value(gb.get("b2", []), aidx), mutation_rate, rng) for aidx in range(len(ACTION_NAMES))],
        "mutation_rate": round(clamp(mutation_rate + rng.gauss(0.0, 0.0012), 0.005, 0.06), 6),
    }
    # Learned plastic changes are deliberately NOT inherited.
    return {
        "schema": CORTEX_SCHEMA_VERSION,
        "kind": "tiny-neural-controller",
        "origin": "sexual inheritance",
        "gate": round(_gate(species, child_genes), 6),
        "plasticity": round(_plasticity(species, child_genes), 6),
        "genome": genome,
        "plastic": {"w2": _zeros_matrix(len(ACTION_NAMES), MAX_HIDDEN), "b2": [0.0 for _ in ACTION_NAMES]},
        "state": {"decisions": 0, "reward_ema": 0.0, "last_reward": 0.0, "last_action": "rest", "last_confidence": 0.0, "last_hidden": [0.0 for _ in range(MAX_HIDDEN)]},
    }


def validate_brain(brain: dict[str, Any]) -> bool:
    if not isinstance(brain, dict) or int(brain.get("schema", 0)) != CORTEX_SCHEMA_VERSION:
        return False
    genome = brain.get("genome", {})
    hidden = int(genome.get("hidden", 0))
    if not MIN_HIDDEN <= hidden <= MAX_HIDDEN:
        return False
    if len(genome.get("w1", [])) != MAX_HIDDEN or len(genome.get("w2", [])) != len(ACTION_NAMES):
        return False
    for row in genome.get("w1", []):
        if len(row) != len(INPUT_NAMES) or any(abs(float(v)) > MAX_WEIGHT + 1e-9 for v in row):
            return False
    for row in genome.get("w2", []):
        if len(row) != MAX_HIDDEN or any(abs(float(v)) > MAX_WEIGHT + 1e-9 for v in row):
            return False
    plastic = brain.get("plastic", {})
    for row in plastic.get("w2", []):
        if any(abs(float(v)) > MAX_PLASTIC + 1e-9 for v in row):
            return False
    return True


def population_summary(agents: list[dict[str, Any]], cohorts: list[dict[str, Any]]) -> dict[str, Any]:
    living = [a for a in agents if a.get("alive", True) and isinstance(a.get("brain"), dict)]
    brains = [a["brain"] for a in living]
    hidden = [int((b.get("genome") or {}).get("hidden", 0)) for b in brains]
    gates = [float(b.get("gate", 0.0)) for b in brains]
    plasticity = [float(b.get("plasticity", 0.0)) for b in brains]
    decisions = [int((b.get("state") or {}).get("decisions", 0)) for b in brains]
    actions: dict[str, int] = {name: 0 for name in ACTION_NAMES}
    for b in brains:
        action = str((b.get("state") or {}).get("last_action", "rest"))
        if action in actions:
            actions[action] += 1
    return {
        "schema": CORTEX_SCHEMA_VERSION,
        "resolved_brains": len(brains),
        "compressed_cohorts": len([c for c in cohorts if float(c.get("count", 0)) > 0 and isinstance(c.get("cortex"), dict)]),
        "mean_hidden_neurons": round(sum(hidden) / len(hidden), 3) if hidden else 0.0,
        "mean_controller_gate": round(sum(gates) / len(gates), 5) if gates else 0.0,
        "mean_plasticity": round(sum(plasticity) / len(plasticity), 5) if plasticity else 0.0,
        "lifetime_decisions": sum(decisions),
        "last_actions": actions,
        "canonical_llm_enabled": False,
    }


def local_llm_status() -> dict[str, Any]:
    url = os.environ.get("PHYLUM_CORTEX_LLM_URL", "").strip()
    model = os.environ.get("PHYLUM_CORTEX_LLM_MODEL", "").strip()
    return {
        "configured": bool(url),
        "url": url or None,
        "model": model or None,
        "canonical_evolution_uses_llm": False,
    }


def probe_local_llm(prompt: str = "Reply with exactly: CORTEX ONLINE") -> dict[str, Any]:
    """Manual-only probe for an OpenAI-compatible local endpoint.

    Set PHYLUM_CORTEX_LLM_URL to a full chat-completions endpoint, e.g.
    http://127.0.0.1:1234/v1/chat/completions.  This function is never called by
    evolve_one/advance_vivarium and therefore cannot silently make Git history
    dependent on an unavailable model.
    """
    status = local_llm_status()
    if not status["configured"]:
        return {**status, "ok": False, "error": "PHYLUM_CORTEX_LLM_URL is not configured"}
    payload = {
        "model": status.get("model") or "local-model",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 24,
    }
    req = urllib.request.Request(str(status["url"]), data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        return {**status, "ok": True, "response": text[:240]}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {**status, "ok": False, "error": str(exc)[:240]}
