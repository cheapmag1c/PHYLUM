import random
import unittest
import copy
from collections import Counter

from phylum.constants import GRID_COLS, GRID_ROWS, TRAIT_BOUNDS
from phylum.storage import load_extended
from phylum.vivarium import (
    GENE_LOCI, MAX_AGENT_MEMORY, MAX_AGENT_SOCIAL, MAX_AGENTS_PER_SPECIES,
    MAX_COHORTS_PER_SPECIES, VIVARIUM_SCHEMA_VERSION, _agent_feed, _inherit_genes,
    _metabolic_cost, _seasonal_anomalies,
    load_vivarium_state, validate_vivarium_state, vivarium_summary,
)
from phylum.vivarium_render import render_vivarium_assets
from phylum.storage import ROOT


class VivariumTests(unittest.TestCase):
    def setUp(self):
        self.world, self.species, self.env, self.pathogens, self.plates, self.branch, self.interactions = load_extended()
        self.state, self.agents, self.cohorts, self.eco = load_vivarium_state()

    def test_engine_state_is_present(self):
        self.assertEqual(self.world.get("engine"), "VIVARIUM")
        self.assertEqual(self.state.get("schema"), VIVARIUM_SCHEMA_VERSION)
        self.assertGreaterEqual(float(self.state.get("sim_day", 0)), 0)

    def test_ecosystem_grid_is_complete(self):
        self.assertGreaterEqual(len(self.eco.get("cells", {})), GRID_COLS * GRID_ROWS)
        for row in list(self.eco.get("cells", {}).values())[:50]:
            self.assertGreaterEqual(float(row.get("producer_biomass", 0)), 0)
            self.assertGreater(float(row.get("capacity", 0)), 0)

    def test_population_is_measured_from_agents_and_cohorts(self):
        counts = Counter()
        for a in self.agents:
            if a.get("alive", True): counts[str(a.get("species_id"))] += 1.0
        for c in self.cohorts:
            if float(c.get("count", 0)) > 0: counts[str(c.get("species_id"))] += float(c.get("count", 0))
        for sp in self.species:
            if sp.get("extinct_generation") is None:
                self.assertAlmostEqual(float(sp.get("population", 0)), counts[str(sp.get("id"))], delta=max(0.12, counts[str(sp.get("id"))] * 0.002))

    def test_agent_ids_and_condition_are_valid(self):
        ids = [str(a.get("id")) for a in self.agents]
        self.assertEqual(len(ids), len(set(ids)))
        for a in self.agents:
            self.assertTrue(0 <= float(a.get("energy", 0)) <= 1)
            self.assertTrue(0 <= float(a.get("health", 0)) <= 1)
            self.assertLessEqual(len(a.get("memory", [])), MAX_AGENT_MEMORY)
            self.assertLessEqual(len(a.get("social", {})), MAX_AGENT_SOCIAL)

    def test_explicit_agents_and_cohorts_are_bounded(self):
        agents = Counter(str(a.get("species_id")) for a in self.agents if a.get("alive", True))
        cohorts = Counter(str(c.get("species_id")) for c in self.cohorts if float(c.get("count", 0)) > 0)
        self.assertTrue(all(n <= MAX_AGENTS_PER_SPECIES for n in agents.values()))
        self.assertTrue(all(n <= MAX_COHORTS_PER_SPECIES for n in cohorts.values()))

    def test_genes_remain_inside_declared_bounds(self):
        samples = [a.get("genes", {}) for a in self.agents[:80]] + [c.get("genes", {}) for c in self.cohorts[:80]]
        for genes in samples:
            for locus in GENE_LOCI:
                lo, hi = TRAIT_BOUNDS[locus]
                self.assertTrue(lo <= float(genes.get(locus, lo)) <= hi, (locus, genes.get(locus)))

    def test_recombination_produces_bounded_offspring(self):
        living = [a for a in self.agents if a.get("alive", True)]
        if len(living) < 2:
            self.skipTest("not enough explicit organisms")
        child = _inherit_genes(living[0], living[1], random.Random(42))
        self.assertEqual(set(child), set(GENE_LOCI))
        for locus, value in child.items():
            lo, hi = TRAIT_BOUNDS[locus]
            self.assertTrue(lo <= value <= hi)

    def test_validation_accepts_current_world(self):
        self.assertEqual(validate_vivarium_state(self.world, self.species), [])

    def test_summary_reports_continuous_time(self):
        row = vivarium_summary(self.world, self.species)
        self.assertEqual(row.get("engine"), "VIVARIUM")
        self.assertIn("sim_day", row)
        self.assertIn("sim_year", row)
        self.assertIn("last_checkpoint", row)

    def test_vivarium_epoch_is_separate_from_legacy_observations(self):
        self.assertIn("epoch_origin_observation", self.state)
        self.assertGreaterEqual(int(self.state.get("legacy_observations", 0)), 0)
        self.assertLessEqual(float(self.state.get("sim_day", 0)), float(self.world.get("generation", 0)) * 60 + 1)

    def test_adapted_autotroph_can_meet_daily_maintenance(self):
        # The engine must not deterministically starve strong primary producers
        # simply because their energy bookkeeping is mis-scaled.
        candidates = [a for a in self.agents if a.get("alive", True) and float(a.get("genes", {}).get("autotrophy", 0)) > 0.65]
        if not candidates:
            self.skipTest("no explicit autotroph")
        agent = copy.deepcopy(candidates[0])
        sp = next(s for s in self.species if str(s.get("id")) == str(agent.get("species_id")))
        key = f"{int(agent['cell'][0])},{int(agent['cell'][1])}"
        cell = copy.deepcopy(self.eco["cells"][key])
        gain = _agent_feed(agent, sp, cell, [], [agent], {str(sp.get("id")): sp}, random.Random(7), [], Counter(), float(self.state.get("sim_day", 0)))
        self.assertGreater(gain, _metabolic_cost(agent, sp) * 0.85)

    def test_public_population_has_no_hidden_species_multiplier(self):
        # Population must be an observation of living state, not a second
        # independently evolving number.
        measured = Counter()
        for a in self.agents:
            if a.get("alive", True): measured[str(a.get("species_id"))] += 1
        for c in self.cohorts:
            measured[str(c.get("species_id"))] += max(0.0, float(c.get("count", 0)))
        public = {str(s.get("id")): float(s.get("population", 0)) for s in self.species if s.get("extinct_generation") is None}
        self.assertEqual(set(public), {k for k,v in measured.items() if v > 0.03})

    def test_seasons_reverse_across_hemispheres(self):
        north_t, _ = _seasonal_anomalies((GRID_COLS//2, 1), 90)
        south_t, _ = _seasonal_anomalies((GRID_COLS//2, GRID_ROWS-2), 90)
        self.assertLess(north_t * south_t, 0)

    def test_living_world_assets_render(self):
        render_vivarium_assets(self.world, self.species, ROOT)
        self.assertTrue((ROOT / "renders" / "vivarium.svg").exists())
        self.assertTrue((ROOT / "docs" / "vivarium.html").exists())
        self.assertTrue((ROOT / "docs" / "vivarium-data.json").exists())


if __name__ == "__main__":
    unittest.main()
