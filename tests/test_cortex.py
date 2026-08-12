from __future__ import annotations

import copy
import random
import unittest
from unittest.mock import patch

from phylum import __version__
from phylum.cortex import (
    ACTION_NAMES,
    CORTEX_SCHEMA_VERSION,
    brain_energy_cost,
    create_brain,
    decide_action,
    ensure_agent_brain,
    ensure_cohort_cortex,
    inherit_brain,
    learn_from_reward,
    local_llm_status,
    population_summary,
    validate_brain,
)
from phylum.storage import load_extended
from phylum.vivarium import ensure_vivarium_state, load_vivarium_state


def species_fixture(complexity: float = 0.5) -> dict:
    return {
        "id": "sp-test",
        "name": "test organism",
        "nerve": {"architecture": {"neural_complexity": complexity, "learning_rate": 0.35}},
    }


def genes_fixture(complexity: float = 0.5) -> dict:
    return {
        "complexity": complexity,
        "sensory": 0.5,
        "recombination": 0.5,
        "temp_pref": 0.5,
        "moisture_pref": 0.5,
        "tolerance": 0.4,
    }


class CortexTests(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(__version__, "2.1.1")

    def test_brain_initialization_is_deterministic(self):
        sp = species_fixture()
        genes = genes_fixture()
        a = create_brain(123, "o-1", sp, genes)
        b = create_brain(123, "o-1", sp, genes)
        self.assertEqual(a, b)
        self.assertTrue(validate_brain(a))

    def test_primitive_controller_has_less_authority(self):
        low = create_brain(1, "low", species_fixture(0.03), genes_fixture(0.03))
        high = create_brain(1, "high", species_fixture(0.90), genes_fixture(0.90))
        self.assertLess(low["gate"], high["gate"])

    def test_decision_is_valid_and_bounded(self):
        sp = species_fixture(0.7)
        agent = {
            "id": "o-2", "species_id": sp["id"], "genes": genes_fixture(0.7),
            "energy": 0.5, "health": 1.0, "stage": "adult", "sex": "A",
            "infections": {}, "memory": [], "alive": True,
        }
        ensure_agent_brain(agent, sp, 2)
        decision = decide_action(agent, sp, {"producer_biomass": 10, "capacity": 20, "temperature": 0.5, "moisture": 0.5}, [], 2, 1.0, random.Random(7))
        self.assertIn(decision["action"], ACTION_NAMES)
        self.assertGreaterEqual(decision["confidence"], 0.0)
        self.assertLessEqual(decision["confidence"], 1.0)

    def test_learning_changes_plastic_state_not_inherited_genome(self):
        sp = species_fixture(0.8)
        agent = {"id": "o-3", "genes": genes_fixture(0.8), "brain": create_brain(4, "o-3", sp, genes_fixture(0.8))}
        before_genome = copy.deepcopy(agent["brain"]["genome"])
        agent["brain"]["state"]["last_action"] = "forage"
        agent["brain"]["state"]["last_hidden"] = [0.5] * 8
        before_plastic = copy.deepcopy(agent["brain"]["plastic"])
        learn_from_reward(agent, 0.8)
        self.assertEqual(agent["brain"]["genome"], before_genome)
        self.assertNotEqual(agent["brain"]["plastic"], before_plastic)
        self.assertTrue(validate_brain(agent["brain"]))

    def test_offspring_inherits_architecture_but_not_learned_plasticity(self):
        sp = species_fixture(0.7)
        genes = genes_fixture(0.7)
        a = {"id": "a", "brain": create_brain(10, "a", sp, genes)}
        b = {"id": "b", "brain": create_brain(10, "b", sp, genes)}
        a["brain"]["plastic"]["b2"][0] = 0.55
        child = inherit_brain(a, b, "c", 10, sp, genes, random.Random(2))
        self.assertEqual(child["schema"], CORTEX_SCHEMA_VERSION)
        self.assertTrue(all(abs(x) < 1e-12 for x in child["plastic"]["b2"]))
        self.assertEqual(child["state"]["decisions"], 0)
        self.assertTrue(validate_brain(child))

    def test_brain_energy_cost_is_small_and_bounded(self):
        sp = species_fixture(1.0)
        brain = create_brain(2, "o", sp, genes_fixture(1.0))
        agent = {"brain": brain, "genes": genes_fixture(1.0)}
        cost = brain_energy_cost(agent, sp)
        self.assertGreaterEqual(cost, 0.0)
        self.assertLess(cost, 0.05)

    def test_cohort_representation_is_compressed(self):
        sp = species_fixture(0.6)
        cohort = {"id": "c-1", "genes": genes_fixture(0.6), "count": 100}
        row = ensure_cohort_cortex(cohort, sp, 7)
        self.assertIn("controller_seed", row)
        self.assertNotIn("w1", row)
        self.assertNotIn("w2", row)
        self.assertLessEqual(row["hidden"], 8)

    def test_current_world_migration_adds_cortex_without_advancing(self):
        world, species, env, pathogens, plates, branch, interactions = load_extended()
        before_obs = int(world.get("generation", 0))
        old_state, _, _, _ = load_vivarium_state()
        before_day = float(old_state.get("sim_day", 0))
        state, agents, cohorts, _ = ensure_vivarium_state(world, species, env, plates, save=False)
        represented = {}
        for agent in agents:
            if agent.get("alive", True):
                sid = str(agent.get("species_id"))
                represented[sid] = represented.get(sid, 0.0) + float(agent.get("weight", 1.0))
        for cohort in cohorts:
            count = float(cohort.get("count", 0))
            if count > 0:
                sid = str(cohort.get("species_id"))
                represented[sid] = represented.get(sid, 0.0) + count
        self.assertEqual(int(world.get("generation", 0)), before_obs)
        self.assertEqual(float(state.get("sim_day", 0)), before_day)
        # VIVARIUM publishes each species population rounded to 3 decimals.
        # Summing those rounded public values can differ slightly from summing
        # the higher-precision cohort counts.  Check the actual invariant per
        # lineage instead of comparing two differently rounded grand totals.
        for sp in species:
            if sp.get("extinct_generation") is not None:
                continue
            sid = str(sp.get("id"))
            self.assertEqual(
                round(represented.get(sid, 0.0), 3),
                round(float(sp.get("population", 0)), 3),
                msg=f"VIVARIUM representation drift for {sid}",
            )
        self.assertTrue(all(isinstance(a.get("brain"), dict) for a in agents if a.get("alive", True)))
        self.assertTrue(all(isinstance(c.get("cortex"), dict) for c in cohorts if float(c.get("count", 0)) > 0))

    def test_local_llm_is_optional_and_never_canonical(self):
        with patch.dict("os.environ", {}, clear=True):
            status = local_llm_status()
        self.assertFalse(status["canonical_evolution_uses_llm"])
        self.assertFalse(status["configured"])

    def test_population_summary_is_bounded(self):
        sp = species_fixture(0.5)
        agent = {"id": "o", "genes": genes_fixture(0.5)}
        ensure_agent_brain(agent, sp, 4)
        cohort = {"id": "c", "genes": genes_fixture(0.5), "count": 30}
        ensure_cohort_cortex(cohort, sp, 4)
        summary = population_summary([agent], [cohort])
        self.assertEqual(summary["resolved_brains"], 1)
        self.assertEqual(summary["compressed_cohorts"], 1)
        self.assertLessEqual(summary["mean_hidden_neurons"], 8)


if __name__ == "__main__":
    unittest.main()
